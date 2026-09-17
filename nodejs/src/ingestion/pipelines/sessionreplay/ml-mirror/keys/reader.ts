import { logger } from '~/common/utils/logger'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'

import { MlDataKey, MlKeyEncryption, openSessionKey } from './crypto'
import { DynamoItem, MlKeyDynamoDB } from './dynamodb'
import {
    MlKeyIdentity,
    TableKey,
    imageKeyId,
    keySessionMonth,
    storedSessionId,
    tableKeyString,
    teamBlockId,
} from './schema'
import { isTransientError } from './transient'

export class MlKeyReader {
    constructor(
        private readonly db: MlKeyDynamoDB,
        private readonly encryption: MlKeyEncryption
    ) {}

    private identityOf(item: DynamoItem): MlKeyIdentity {
        const teamId = Number(item.team_id?.N)
        if (!Number.isSafeInteger(teamId)) {
            throw new Error('Invalid ML key record')
        }
        const sessionId = item.sk.S ? storedSessionId(item.sk.S) : undefined
        const organizationId = item.organization_id?.S
        return {
            teamId,
            ...(sessionId ? { sessionId } : { sessionMonth: item.session_month?.S }),
            ...(organizationId ? { organizationId } : {}),
        }
    }

    /** The writer seals under the month it takes from the session id, so the reader takes the month the same way. */
    private monthKeyIdFor(identity: MlKeyIdentity): string | undefined {
        try {
            return tableKeyString(imageKeyId(identity.teamId, keySessionMonth(identity)))
        } catch {
            return undefined
        }
    }

    public async read(keys: TableKey[]): Promise<Map<string, MlDataKey>> {
        const stored = await this.db.read(keys)
        const identities = new Map<string, MlKeyIdentity>()
        for (const [id, item] of stored) {
            if (item.deleted?.BOOL === true || !(item.wrapped_key?.B || (item.sealed_key?.B && item.key_nonce?.B))) {
                continue
            }
            identities.set(id, this.identityOf(item))
        }
        // A sealed session key opens under its team month key, so this read includes that row with the team blocks.
        const monthKeys = new Map<string, TableKey>()
        const monthKeyOf = new Map<string, string>()
        for (const [id, identity] of identities) {
            if (!stored.get(id)!.sealed_key?.B) {
                continue
            }
            const monthId = this.monthKeyIdFor(identity)
            if (!monthId) {
                continue
            }
            monthKeyOf.set(id, monthId)
            monthKeys.set(monthId, imageKeyId(identity.teamId, keySessionMonth(identity)))
        }
        const state = await this.db.read([
            ...[...identities.values()].map((identity) => teamBlockId(identity.teamId)),
            ...monthKeys.values(),
        ])
        const blocked = (teamId: number): boolean => state.has(tableKeyString(teamBlockId(teamId)))
        const months = new Map<string, MlDataKey>()
        const refused: { id: string; error: string }[] = []
        await Promise.all(
            [...monthKeys.keys()].map(async (id) => {
                const item = state.get(id)
                if (!item?.wrapped_key?.B || item.deleted?.BOOL === true) {
                    return
                }
                try {
                    const identity = this.identityOf(item)
                    if (blocked(identity.teamId)) {
                        return
                    }
                    months.set(id, await this.encryption.decrypt(identity, Buffer.from(item.wrapped_key.B)))
                } catch (error) {
                    // A throttled KMS must fail the read so the caller retries. A month key that can never open must not stall every session in the batch.
                    if (isTransientError(error)) {
                        throw error
                    }
                    refused.push({ id, error: error instanceof Error ? error.name : String(error) })
                }
            })
        )
        const missing = [...monthKeys.keys()].filter((id) => !months.has(id))
        if (missing.length) {
            MlMirrorMetrics.incrementMlKeyIdentityMismatch('month_key_unavailable', missing.length)
        }
        if (refused.length) {
            logger.error('🔑', 'ml_key_month_key_refused', { count: refused.length, rows: refused })
        }
        const result = new Map<string, MlDataKey>()
        await Promise.all(
            [...identities].map(async ([id, identity]) => {
                if (blocked(identity.teamId)) {
                    return
                }
                const item = stored.get(id)!
                if (item.sealed_key?.B && item.key_nonce?.B) {
                    const monthId = monthKeyOf.get(id)
                    const month = monthId ? months.get(monthId) : undefined
                    if (!month) {
                        return
                    }
                    const sealed = { sealed: Buffer.from(item.sealed_key.B), nonce: Buffer.from(item.key_nonce.B) }
                    try {
                        const plaintext = openSessionKey(month.plaintext, identity, sealed)
                        MlMirrorMetrics.incrementMlKeyScheme('v3')
                        result.set(id, { identity, plaintext, wrapped: Buffer.alloc(0) })
                    } catch {
                        // One row that disagrees with its month key must not fail the read for every other session.
                        MlMirrorMetrics.incrementMlKeyIdentityMismatch('seal_unopenable', 1)
                    }
                    return
                }
                if (identity.sessionId) {
                    MlMirrorMetrics.incrementMlKeyScheme('v2')
                }
                result.set(id, await this.encryption.decrypt(identity, Buffer.from(item.wrapped_key!.B!)))
            })
        )
        return result
    }
}
