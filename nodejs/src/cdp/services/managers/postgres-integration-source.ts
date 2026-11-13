import { IntegrationType } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { IntegrationReference, legacyIdOfReference } from '~/cdp/utils/integration-reference'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

import { IntegrationDecryptFailure, IntegrationSource, IntegrationSourceRecord } from './integration-source'

// Fernet tokens start with the version byte 0x80 and a timestamp, so base64 gives this prefix.
// Python uses the same marker in `posthog/helpers/encrypted_fields.py`.
const FERNET_TOKEN_PREFIX = 'gAAAAA'

type DecryptedConfig = {
    sensitiveConfig: Record<string, any>
    failures: IntegrationDecryptFailure[]
}

/** Reads `posthog_integration` and decrypts `sensitive_config` with the Node Fernet keys. */
export class PostgresIntegrationSource implements IntegrationSource {
    public readonly name = 'postgres'

    constructor(
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields
    ) {}

    public async load(
        references: IntegrationReference[]
    ): Promise<Record<IntegrationReference, IntegrationSourceRecord>> {
        // A UUID reference has no row in this table, so it is not found.
        const legacyIds = references.map(legacyIdOfReference).filter((id): id is number => id !== null)
        if (legacyIds.length === 0) {
            return {}
        }

        // The cast keeps an id past the int4 range from failing the whole batch.
        const response = await this.postgres.query<IntegrationType>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, kind, config, sensitive_config FROM posthog_integration WHERE id = ANY($1::bigint[])`,
            [legacyIds],
            'fetchIntegrations'
        )

        const records: Record<IntegrationReference, IntegrationSourceRecord> = {}
        for (const row of response.rows) {
            const { sensitiveConfig, failures } = this.decryptSensitiveConfig(row.sensitive_config || {})
            const reference = String(row.id)
            records[reference] = {
                reference,
                integration: { ...row, sensitive_config: sensitiveConfig },
                decryptFailures: failures,
            }
        }
        return records
    }

    /**
     * Gives the same values as `decryptObject` with `ignoreDecryptionErrors`: a value that does not
     * decrypt stays as it is. Plain values are not encrypted, so only a value that looks like a
     * Fernet token counts as a failure.
     */
    private decryptSensitiveConfig(sensitiveConfig: Record<string, any>): DecryptedConfig {
        const failures: IntegrationDecryptFailure[] = []

        const decryptValue = (value: any, path: string): any => {
            if (typeof value === 'string') {
                const result = this.encryptedFields.tryDecrypt(value)
                if (!result.ok) {
                    if (value.startsWith(FERNET_TOKEN_PREFIX)) {
                        failures.push({ path, reason: 'undecryptable' })
                    }
                    return value
                }
                if (result.value.startsWith(FERNET_TOKEN_PREFIX)) {
                    failures.push({ path, reason: 'nested_ciphertext' })
                }
                return result.value
            }
            if (value === null || value === undefined) {
                return value
            }
            if (Array.isArray(value)) {
                return value.map((item, index) => decryptValue(item, `${path}.${index}`))
            }
            if (typeof value === 'object') {
                return Object.fromEntries(
                    Object.entries(value).map(([key, item]) => [key, decryptValue(item, path ? `${path}.${key}` : key)])
                )
            }
            return value
        }

        return { sensitiveConfig: decryptValue(sensitiveConfig, ''), failures }
    }
}
