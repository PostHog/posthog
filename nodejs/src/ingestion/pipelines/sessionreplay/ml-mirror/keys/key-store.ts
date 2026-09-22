import { randomBytes } from 'node:crypto'

import { logger } from '~/common/utils/logger'
import { MlKeyIdentityMismatchReason, MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
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
            sessionKeyId(identity.teamId, identity.sessionId),
            imageKeyId(identity.teamId, sessionStartMonth(identity.sessionId)),
        ])
        this.state = await this.db.read(initial, deadline)
        const keyIdentities = new Map<string, MlKeyIdentity>()
        for (const identity of this.identities) {
            const id = tableKeyString(sessionKeyId(identity.teamId, identity.sessionId))
            if (this.state.get(id)?.deleted?.BOOL === true) {
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
                        if (typeof stored === 'string') {
                            const rowNeedsRepair = stored !== 'month_key_unavailable'
                            if (this.reportUnusable(id, stored) && rowNeedsRepair) {
                                unusable.push({ id, teamId: identity.teamId })
                            }
                            return
                        }
                        this.keys.set(id, stored)
                    } else {
                        // A shredded team image key stops its team month for good, which is why no team block row exists. See products/ai_training/docs/replay-data.md.
                        if (identity.sessionId && !this.monthKeyFor(identity)) {
                            this.reportUnusable(id, 'month_key_unavailable')
                            return
                        }
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
        // A row that gives no key cannot serve this batch; its sessions are dropped like blocked ones so one bad row cannot stop the lane, and the log names it so the data can be repaired.
        if (unusable.length) {
            logger.error('🔑', 'ml_key_stored_key_unusable', {
                count: unusable.length,
                teamIds: [...new Set(unusable.map((entry) => entry.teamId))],
                rows: unusable.map((entry) => entry.id),
            })
        }
    }

    private reportUnusable(id: string, reason: MlKeyIdentityMismatchReason): boolean {
        if (this.reportedUnusable.has(id)) {
            return false
        }
        this.reportedUnusable.add(id)
        MlMirrorMetrics.incrementMlKeyIdentityMismatch(reason, 1)
        return true
    }

    private monthKeyFor(identity: MlKeyIdentity): MlDataKey | undefined {
        return this.keys.get(tableKeyString(imageKeyId(identity.teamId, keySessionMonth(identity))))
    }

    /** Resolves a stored row to its key, whether KMS wrapped it or its team month key sealed it. */
    private async openStored(
        identity: MlKeyIdentity,
        item: DynamoItem
    ): Promise<MlDataKey | MlKeyIdentityMismatchReason> {
        if (item.sealed_key?.B && item.key_nonce?.B) {
            const monthKey = this.monthKeyFor(identity)
            if (!monthKey) {
                return 'month_key_unavailable'
            }
            const sealed = { sealed: Buffer.from(item.sealed_key.B), nonce: Buffer.from(item.key_nonce.B) }
            try {
                const plaintext = openSessionKey(monthKey.plaintext, identity, sealed)
                MlMirrorMetrics.incrementMlKeyScheme('v3')
                return { identity, plaintext, wrapped: Buffer.alloc(0) }
            } catch {
                // A seal opens under one month key only, so a failure here means the row and the month key disagree. One row must not stop the lane.
                return 'seal_unopenable'
            }
        }
        if (!item.wrapped_key?.B) {
            return 'wrapped_key_missing'
        }
        if (identity.sessionId) {
            MlMirrorMetrics.incrementMlKeyScheme('v2')
        }
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
        let dropped = 0
        const rows: [string, MlDataKey, DynamoItem][] = []
        for (const [id, key] of entries) {
            const row = this.rowFor(key)
            if (!row) {
                this.keys.delete(id)
                dropped += 1
                continue
            }
            rows.push([id, key, row])
        }
        if (!rows.length) {
            this.reportDropped(dropped)
            return
        }
        // Every index entry goes in before any key, so a key put that fails still leaves its entry. These need no
        // condition, so they batch and a key costs one write request rather than two.
        await this.db.putMany(
            rows.map(([, key]) => {
                const location = storedKeyId(key.identity)
                return {
                    key: monthKeyIndexId(key.identity, location),
                    attributes: { key_pk: { S: location.pk }, key_sk: { S: location.sk } },
                }
            }),
            deadline
        )
        const results = await Promise.allSettled(
            rows.map(async ([id, key, row]) => {
                const location = storedKeyId(key.identity)
                const stored = await this.db.putIfAbsent(location, row, deadline)
                if (!stored) {
                    this.encryption.rememberCommitted(key)
                    return
                }
                // Batches overlap, so a later batch reads before an earlier one writes, and a new session routinely meets its own earlier candidate here.
                if (stored.deleted?.BOOL === true) {
                    this.keys.delete(id)
                    dropped += 1
                    return
                }
                // A wrapped blob is stable, so equal bytes name this batch's own write and spare a KMS decrypt.
                if (
                    key.wrapped.length &&
                    stored.wrapped_key?.B &&
                    key.wrapped.equals(Buffer.from(stored.wrapped_key.B))
                ) {
                    this.encryption.rememberCommitted(key)
                    return
                }
                const winner = await this.openStored(key.identity, stored)
                if (typeof winner === 'string') {
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
        this.reportDropped(dropped)
    }

    private reportDropped(dropped: number): void {
        if (dropped) {
            logger.info('🔑', 'ml_key_commit_dropped_blocked', { dropped })
        }
    }

    /** A month key keeps its KMS blob. A session key carries the seal its month key made, so it gives no row once that month key goes. */
    private rowFor(key: MlDataKey): DynamoItem | undefined {
        const shared = {
            team_id: { N: String(key.identity.teamId) },
            session_month: { S: keySessionMonth(key.identity) },
        }
        if (!key.identity.sessionId) {
            if (!key.wrapped.length) {
                throw new Error('ML month key has no KMS blob to store')
            }
            return { wrapped_key: { B: key.wrapped }, ...shared }
        }
        const monthKey = this.monthKeyFor(key.identity)
        if (!monthKey) {
            return undefined
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
