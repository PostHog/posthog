import { KEY_READ_LEASE_MS, MlDataKey, MlKeyEncryption } from './crypto'
import { MlPrivacyDynamoDB } from './dynamodb'
import {
    MlKeyIdentity,
    TableKey,
    consentKeyId,
    keySessionMonth,
    monthBlockId,
    tableKeyString,
    teamBlockId,
} from './schema'

export class MlKeyReader {
    constructor(
        private readonly db: MlPrivacyDynamoDB,
        private readonly encryption: MlKeyEncryption
    ) {}

    public async read(keys: TableKey[]): Promise<Map<string, MlDataKey>> {
        const decryptUntil = performance.now() + KEY_READ_LEASE_MS
        const stored = await this.db.read(keys)
        const identities = new Map<string, MlKeyIdentity>()
        for (const [id, item] of stored) {
            if (!item.wrapped_key?.B || item.deleted?.BOOL === true) {
                continue
            }
            const teamId = Number(item.team_id?.N)
            const organizationId = item.organization_id?.S
            const consentGrantedAt = Number(item.granted_at?.N)
            if (!Number.isSafeInteger(teamId) || !organizationId || !Number.isSafeInteger(consentGrantedAt)) {
                throw new Error('Invalid ML key record')
            }
            const sessionId = item.sk.S?.startsWith('session:') ? item.sk.S.slice('session:'.length) : undefined
            identities.set(id, {
                teamId,
                organizationId,
                consentGrantedAt,
                ...(sessionId ? { sessionId } : { sessionMonth: item.session_month?.S }),
            })
        }
        const state = await this.db.read(
            [...identities.values()].flatMap((identity) => [
                monthBlockId(keySessionMonth(identity)),
                consentKeyId(identity.organizationId),
                teamBlockId(identity.teamId),
            ])
        )
        const result = new Map<string, MlDataKey>()
        await Promise.all(
            [...identities].map(async ([id, identity]) => {
                const consent = state.get(tableKeyString(consentKeyId(identity.organizationId)))
                if (
                    state.has(tableKeyString(monthBlockId(keySessionMonth(identity)))) ||
                    state.has(tableKeyString(teamBlockId(identity.teamId))) ||
                    consent?.allowed?.BOOL !== true ||
                    Number(consent.granted_at?.N) !== identity.consentGrantedAt
                ) {
                    return
                }
                result.set(id, {
                    ...(await this.encryption.decrypt(identity, Buffer.from(stored.get(id)!.wrapped_key.B!))),
                    decryptUntil,
                })
            })
        )
        return result
    }
}
