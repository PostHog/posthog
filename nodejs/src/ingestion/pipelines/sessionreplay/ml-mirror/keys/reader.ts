import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'

import { MlDataKey, MlKeyEncryption, openSessionKey } from './crypto'
import { DynamoItem, MlKeyDynamoDB } from './dynamodb'
import { MlKeyIdentity, TableKey, imageKeyId, storedSessionId, tableKeyString, teamBlockId } from './schema'

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
        for (const [id, identity] of identities) {
            const month = stored.get(id)!.sealed_key?.B ? stored.get(id)!.session_month?.S : undefined
            if (month) {
                const key = imageKeyId(identity.teamId, month)
                monthKeys.set(tableKeyString(key), key)
            }
        }
        const state = await this.db.read([
            ...[...identities.values()].map((identity) => teamBlockId(identity.teamId)),
            ...monthKeys.values(),
        ])
        const months = new Map<string, MlDataKey>()
        await Promise.all(
            [...monthKeys.keys()].map(async (id) => {
                const item = state.get(id)
                if (!item?.wrapped_key?.B || item.deleted?.BOOL === true) {
                    return
                }
                months.set(id, await this.encryption.decrypt(this.identityOf(item), Buffer.from(item.wrapped_key.B)))
            })
        )
        const result = new Map<string, MlDataKey>()
        await Promise.all(
            [...identities].map(async ([id, identity]) => {
                if (state.has(tableKeyString(teamBlockId(identity.teamId)))) {
                    return
                }
                const item = stored.get(id)!
                if (item.sealed_key?.B && item.key_nonce?.B) {
                    MlMirrorMetrics.incrementMlKeyScheme('v3')
                    const month = months.get(tableKeyString(imageKeyId(identity.teamId, String(item.session_month?.S))))
                    if (!month) {
                        return
                    }
                    const sealed = { sealed: Buffer.from(item.sealed_key.B), nonce: Buffer.from(item.key_nonce.B) }
                    result.set(id, {
                        identity,
                        plaintext: openSessionKey(month.plaintext, identity, sealed),
                        wrapped: Buffer.alloc(0),
                    })
                    return
                }
                MlMirrorMetrics.incrementMlKeyScheme('v2')
                result.set(id, await this.encryption.decrypt(identity, Buffer.from(item.wrapped_key!.B!)))
            })
        )
        return result
    }
}
