import { logger } from '~/common/utils/logger'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey, MlKeyEncryption } from './crypto'
import { DynamoItem, MlKeyDynamoDB } from './dynamodb'
import {
    MlKeyIdentity,
    MlSessionIdentity,
    TableKey,
    imageKeyId,
    keySessionMonth,
    monthKeyIndexId,
    sessionKeyId,
    tableKeyString,
    teamBlockId,
} from './schema'
import { isTransientError } from './transient'

// Commits retry transient DynamoDB and KMS failures; the budget counts the re-reads as well as the waits and stays under the consumer's loop stall threshold.
const COMMIT_ATTEMPTS = 10
const COMMIT_BUDGET_MS = 45_000
const COMMIT_BACKOFF_BASE_MS = 100
const COMMIT_BACKOFF_CAP_MS = 3_000

function commitRetryDelayMs(attempt: number): number {
    return Math.random() * Math.min(COMMIT_BACKOFF_CAP_MS, COMMIT_BACKOFF_BASE_MS * 2 ** attempt)
}

export interface MlSessionKeys {
    session: MlDataKey
    image: MlDataKey
}

interface MlStoredKeyMismatch {
    id: string
    teamId: number
}

function storedKeyId(identity: MlKeyIdentity): TableKey {
    return identity.sessionId
        ? sessionKeyId(identity.teamId, identity.sessionId)
        : imageKeyId(identity.teamId, keySessionMonth(identity))
}

export class MlSessionKeyStore {
    constructor(
        private readonly db: MlKeyDynamoDB,
        private readonly encryption: MlKeyEncryption
    ) {}

    public async prepare(identities: MlSessionIdentity[]): Promise<MlKeyBatch> {
        const eligible = identities.filter((identity) => {
            try {
                sessionStartMonth(identity.sessionId)
                return true
            } catch {
                return false
            }
        })
        const batch = new MlKeyBatch(this.db, this.encryption, eligible)
        await batch.read()
        return batch
    }
}

export class MlKeyBatch {
    private state = new Map<string, DynamoItem>()
    private readonly candidates = new Map<string, MlDataKey>()
    private readonly keys = new Map<string, MlDataKey>()
    private committed = false
    // persist re-reads the batch after its writes and on every retry, so a row is reported the first time this batch meets it and not on each pass.
    private readonly reportedUnusable = new Set<string>()

    constructor(
        private readonly db: MlKeyDynamoDB,
        private readonly encryption: MlKeyEncryption,
        private readonly identities: MlSessionIdentity[]
    ) {}

    public async read(deadline?: AbortSignal): Promise<void> {
        this.keys.clear()
        const initial = this.identities.flatMap((identity) => [
            teamBlockId(identity.teamId),
            sessionKeyId(identity.teamId, identity.sessionId),
        ])
        this.state = await this.db.read(initial, deadline)
        const keyIdentities = new Map<string, MlKeyIdentity>()
        for (const identity of this.identities) {
            const id = tableKeyString(sessionKeyId(identity.teamId, identity.sessionId))
            if (
                this.state.has(tableKeyString(teamBlockId(identity.teamId))) ||
                this.state.get(id)?.deleted?.BOOL === true
            ) {
                continue
            }
            for (const sessionId of [identity.sessionId, undefined]) {
                const keyIdentity = {
                    teamId: identity.teamId,
                    ...(sessionId ? { sessionId } : { sessionMonth: sessionStartMonth(identity.sessionId) }),
                }
                keyIdentities.set(tableKeyString(storedKeyId(keyIdentity)), keyIdentity)
            }
        }
        const remaining = [...keyIdentities.values()].filter((identity) => !identity.sessionId).map(storedKeyId)
        for (const [id, item] of await this.db.read(remaining, deadline)) {
            this.state.set(id, item)
        }
        const unusable: MlStoredKeyMismatch[] = []
        await Promise.all(
            [...keyIdentities].map(async ([id, identity]) => {
                const item = this.state.get(id)
                if (item?.deleted?.BOOL === true) {
                    return
                }
                if (item) {
                    if (!item.wrapped_key?.B) {
                        if (!this.reportedUnusable.has(id)) {
                            this.reportedUnusable.add(id)
                            unusable.push({ id, teamId: identity.teamId })
                        }
                        return
                    }
                    // A key wrapped while the organization was part of the KMS context only unwraps under that organization, which the row still names.
                    const organizationId = item.organization_id?.S
                    const storedIdentity = { ...identity, ...(organizationId ? { organizationId } : {}) }
                    this.keys.set(id, await this.encryption.decrypt(storedIdentity, Buffer.from(item.wrapped_key.B)))
                } else {
                    let candidate = this.candidates.get(id)
                    if (!candidate) {
                        candidate = await this.encryption.generate(identity)
                        this.candidates.set(id, candidate)
                    }
                    this.keys.set(id, candidate)
                }
            })
        )
        // A row with no wrapped key and no tombstone cannot serve this batch; its sessions are dropped like blocked ones so one bad row cannot stop the lane, and the log names it so the data can be repaired.
        if (unusable.length) {
            MlMirrorMetrics.incrementMlKeyIdentityMismatch('wrapped_key_missing', unusable.length)
            logger.error('🔑', 'ml_key_stored_key_unusable', {
                count: unusable.length,
                teamIds: [...new Set(unusable.map((entry) => entry.teamId))],
                rows: unusable.map((entry) => entry.id),
            })
        }
    }

    public get(teamId: number, sessionId: string): MlSessionKeys | undefined {
        const id = tableKeyString(sessionKeyId(teamId, sessionId))
        const session = this.keys.get(id)
        if (!session) {
            return undefined
        }
        const image = this.keys.get(tableKeyString(imageKeyId(teamId, sessionStartMonth(sessionId))))
        return image ? { session, image } : undefined
    }

    // The index entry goes first and is idempotent, so every stored key has an index entry even when the key put fails or a retried put reports the batch's own write as a competitor's. An index entry without a key is harmless: the month sweep leaves a tombstone that a later key put respects.
    private async persist(deadline: AbortSignal): Promise<void> {
        let dropped = 0
        const unstored = [...this.keys].filter(([id]) => !this.state.has(id))
        // Every index entry goes in before any key, so a key put that fails still leaves its entry, as it did when each
        // key wrote its own. These need no condition, so they batch and a key costs one write request rather than two.
        await this.db.putMany(
            unstored.map(([, key]) => {
                const location = storedKeyId(key.identity)
                return {
                    key: monthKeyIndexId(key.identity, location),
                    attributes: { key_pk: { S: location.pk }, key_sk: { S: location.sk } },
                }
            }),
            deadline
        )
        const results = await Promise.allSettled(
            unstored.map(async ([id, key]) => {
                const location = storedKeyId(key.identity)
                const stored = await this.db.putIfAbsent(
                    location,
                    {
                        wrapped_key: { B: key.wrapped },
                        team_id: { N: String(key.identity.teamId) },
                        session_month: { S: keySessionMonth(key.identity) },
                    },
                    deadline
                )
                if (!stored) {
                    this.encryption.rememberCommitted(key)
                    return
                }
                // A session keys its own partition, so only a rebalance overlap or a team key puts two writers on one row.
                if (!stored.wrapped_key?.B || stored.deleted?.BOOL === true) {
                    this.keys.delete(id)
                    dropped += 1
                    return
                }
                const wrapped = Buffer.from(stored.wrapped_key.B)
                if (wrapped.equals(key.wrapped)) {
                    this.encryption.rememberCommitted(key)
                    return
                }
                const organizationId = stored.organization_id?.S
                const identity = { ...key.identity, ...(organizationId ? { organizationId } : {}) }
                this.keys.set(id, await this.encryption.decrypt(identity, wrapped))
            })
        )
        const failures = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected')
        const failure = failures.find(({ reason }) => !isTransientError(reason)) ?? failures[0]
        if (failure) {
            throw failure.reason
        }
        if (dropped) {
            logger.info('🔑', 'ml_key_commit_dropped_blocked', { dropped })
        }
    }

    public async commit(): Promise<void> {
        if (this.committed) {
            throw new Error('ML batch already committed')
        }
        const startedAt = Date.now()
        const deadline = AbortSignal.timeout(COMMIT_BUDGET_MS)
        for (let attempt = 0; attempt < COMMIT_ATTEMPTS; attempt++) {
            try {
                await this.persist(deadline)
                this.committed = true
                return
            } catch (error) {
                const delayMs = commitRetryDelayMs(attempt)
                if (
                    !isTransientError(error) ||
                    deadline.aborted ||
                    attempt === COMMIT_ATTEMPTS - 1 ||
                    Date.now() - startedAt + delayMs > COMMIT_BUDGET_MS
                ) {
                    throw error
                }
                logger.warn('🔑', 'ml_key_commit_retry', {
                    attempt: attempt + 1,
                    errorName: error instanceof Error ? error.name : undefined,
                    error: String(error),
                })
                await new Promise((resolve) => setTimeout(resolve, delayMs))
                await this.read(deadline)
            }
        }
    }
}
