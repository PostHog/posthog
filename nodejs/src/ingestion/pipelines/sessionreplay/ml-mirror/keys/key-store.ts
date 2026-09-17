import { randomBytes } from 'node:crypto'

import { logger } from '~/common/utils/logger'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey, MlKeyEncryption, openSessionKey, sealSessionKey } from './crypto'
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
        // The image key is the session's start month, so every row this batch needs is known before the first read.
        const initial = this.identities.flatMap((identity) => [
            teamBlockId(identity.teamId),
            sessionKeyId(identity.teamId, identity.sessionId),
            imageKeyId(identity.teamId, sessionStartMonth(identity.sessionId)),
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
        const unusable: MlStoredKeyMismatch[] = []
        // A session key opens under its team month key, so the month keys resolve first.
        for (const group of [
            [...keyIdentities].filter(([, identity]) => !identity.sessionId),
            [...keyIdentities].filter(([, identity]) => identity.sessionId),
        ]) {
            await Promise.all(
                group.map(async ([id, identity]) => {
                    const item = this.state.get(id)
                    if (item?.deleted?.BOOL === true) {
                        return
                    }
                    if (item) {
                        const stored = await this.openStored(identity, item)
                        if (!stored) {
                            if (!this.reportedUnusable.has(id)) {
                                this.reportedUnusable.add(id)
                                unusable.push({ id, teamId: identity.teamId })
                            }
                            return
                        }
                        this.keys.set(id, stored)
                    } else {
                        let candidate = this.candidates.get(id)
                        if (!candidate) {
                            candidate = identity.sessionId
                                ? { identity, plaintext: randomBytes(32), wrapped: Buffer.alloc(0) }
                                : await this.encryption.generate(identity)
                            this.candidates.set(id, candidate)
                        }
                        this.keys.set(id, candidate)
                    }
                })
            )
        }
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

    private monthKeyFor(identity: MlKeyIdentity): MlDataKey | undefined {
        return this.keys.get(tableKeyString(imageKeyId(identity.teamId, keySessionMonth(identity))))
    }

    /** Resolves a stored row to its key, whether KMS wrapped it or its team month key sealed it. */
    private async openStored(identity: MlKeyIdentity, item: DynamoItem): Promise<MlDataKey | undefined> {
        if (item.sealed_key?.B && item.key_nonce?.B) {
            MlMirrorMetrics.incrementMlKeyScheme('v3')
            const monthKey = this.monthKeyFor(identity)
            if (!monthKey) {
                return undefined
            }
            const sealed = { sealed: Buffer.from(item.sealed_key.B), nonce: Buffer.from(item.key_nonce.B) }
            return {
                identity,
                plaintext: openSessionKey(monthKey.plaintext, identity, sealed),
                wrapped: Buffer.alloc(0),
            }
        }
        if (!item.wrapped_key?.B) {
            return undefined
        }
        MlMirrorMetrics.incrementMlKeyScheme('v2')
        // A key wrapped while the organization was part of the KMS context only unwraps under that organization, which the row still names.
        const organizationId = item.organization_id?.S
        const storedIdentity = { ...identity, ...(organizationId ? { organizationId } : {}) }
        return this.encryption.decrypt(storedIdentity, Buffer.from(item.wrapped_key.B))
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
        const unstored = [...this.keys].filter(([id]) => !this.state.has(id))
        // The month key commits first. A put that loses leaves session keys sealed under bytes that nobody stored.
        const monthKeys = unstored.filter(([, key]) => !key.identity.sessionId)
        if (monthKeys.length) {
            await this.write(monthKeys, deadline)
        }
        await this.write(
            unstored.filter(([, key]) => key.identity.sessionId),
            deadline
        )
    }

    private async write(entries: [string, MlDataKey][], deadline: AbortSignal): Promise<void> {
        if (!entries.length) {
            return
        }
        let dropped = 0
        // Every index entry goes in before any key, so a key put that fails still leaves its entry. These need no
        // condition, so they batch and a key costs one write request rather than two.
        await this.db.putMany(
            entries.map(([, key]) => {
                const location = storedKeyId(key.identity)
                return {
                    key: monthKeyIndexId(key.identity, location),
                    attributes: { key_pk: { S: location.pk }, key_sk: { S: location.sk } },
                }
            }),
            deadline
        )
        const results = await Promise.allSettled(
            entries.map(async ([id, key]) => {
                const location = storedKeyId(key.identity)
                const stored = await this.db.putIfAbsent(location, this.rowFor(key), deadline)
                if (!stored) {
                    this.encryption.rememberCommitted(key)
                    return
                }
                // A session keys its own partition, so only a rebalance overlap or a team key puts two writers on one row.
                const winner = stored.deleted?.BOOL === true ? undefined : await this.openStored(key.identity, stored)
                if (!winner) {
                    this.keys.delete(id)
                    dropped += 1
                    return
                }
                if (winner.plaintext.equals(key.plaintext)) {
                    this.encryption.rememberCommitted(key)
                    return
                }
                this.keys.set(id, winner)
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

    /** A month key keeps its KMS blob. A session key carries the seal its month key made. */
    private rowFor(key: MlDataKey): DynamoItem {
        const shared = {
            team_id: { N: String(key.identity.teamId) },
            session_month: { S: keySessionMonth(key.identity) },
        }
        if (!key.identity.sessionId) {
            return { wrapped_key: { B: key.wrapped }, ...shared }
        }
        const monthKey = this.monthKeyFor(key.identity)
        if (!monthKey) {
            throw new Error('ML session key has no team month key to seal it')
        }
        const sealed = sealSessionKey(monthKey.plaintext, key.identity, key.plaintext)
        return { sealed_key: { B: sealed.sealed }, key_nonce: { B: sealed.nonce }, ...shared }
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
