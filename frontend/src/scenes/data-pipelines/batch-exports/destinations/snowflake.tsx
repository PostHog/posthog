import { LemonBanner, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

// New Snowflake exports must store credentials in a linked Integration. Exports created before
// integrations existed keep their inline credentials (grandfathered), detected by integration_id.
export const snowflakeDefinition: DestinationDefinition = {
    type: 'Snowflake',
    usesIntegration: true,
    defaults: () => ({}),
    requiredFields: ({ isNew, formValues }) => {
        if (isNew || formValues.integration_id) {
            // New exports must pick an integration; existing integration-backed exports keep theirs.
            return [...(isNew ? ['integration_id'] : []), 'database', 'warehouse', 'schema', 'table_name']
        }
        // Grandfathered inline-credential exports keep their original fields when edited.
        return ['account', 'database', 'warehouse', 'schema', 'table_name']
    },
    // The credential keys remain allowlisted for grandfathered inline exports.
    // TODO: clean up once fully migrated to integration-based credentials
    configKeys: [
        'database',
        'warehouse',
        'schema',
        'table_name',
        'role',
        'account',
        'user',
        'authentication_type',
        'password',
        'private_key',
        'private_key_passphrase',
    ],
    eventTableOverrides: {
        setName: 'people_set',
        setOnceName: 'people_set_once',
    },
    eventTableExtraFields: {
        snowflake_ingested_timestamp: {
            name: 'snowflake_ingested_timestamp',
            hogql_value: 'NOW64()',
            type: 'datetime',
            schema_valid: true,
        },
    },
    Fields: function SnowflakeFields({ isNew, formValues }) {
        const useIntegration = isNew || !!formValues.integration_id

        return (
            <>
                {useIntegration ? (
                    <LemonField name="integration_id" label="Connection">
                        {({ value, onChange }) => (
                            <IntegrationChoice integration="snowflake" value={value} onChange={onChange} />
                        )}
                    </LemonField>
                ) : (
                    <>
                        <LemonBanner type="warning">
                            Snowflake batch exports are moving to integration-based credentials. This export will be
                            migrated automatically — no action required.
                        </LemonBanner>

                        <LemonField name="account" label="Account">
                            <LemonInput placeholder="my-account" />
                        </LemonField>

                        <LemonField name="user" label="User">
                            <LemonInput placeholder={isNew ? 'my-user' : 'Leave unchanged'} />
                        </LemonField>

                        <LemonField name="authentication_type" label="Authentication type" className="flex-1">
                            <LemonSelect
                                options={[
                                    { value: 'password', label: 'Password' },
                                    { value: 'keypair', label: 'Key pair' },
                                ]}
                            />
                        </LemonField>

                        {formValues.authentication_type != 'keypair' && (
                            <LemonField name="password" label="Password">
                                <LemonInput placeholder={isNew ? 'my-password' : 'Leave unchanged'} type="password" />
                            </LemonField>
                        )}

                        {formValues.authentication_type == 'keypair' && (
                            <>
                                <LemonField name="private_key" label="Private key">
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        placeholder={isNew ? 'my-private-key' : 'Leave unchanged'}
                                        minRows={4}
                                    />
                                </LemonField>

                                <LemonField name="private_key_passphrase" label="Private key passphrase">
                                    <LemonInput placeholder={isNew ? 'my-passphrase' : 'Leave unchanged'} />
                                </LemonField>
                            </>
                        )}
                    </>
                )}

                <LemonField name="database" label="Database">
                    <LemonInput placeholder="my-database" />
                </LemonField>

                <LemonField name="schema" label="Schema">
                    <LemonInput placeholder="my-schema" />
                </LemonField>

                <LemonField name="table_name" label="Table name">
                    <LemonInput placeholder="events" />
                </LemonField>

                <LemonField name="warehouse" label="Warehouse">
                    <LemonInput placeholder="my-warehouse" />
                </LemonField>

                <LemonField name="role" label="Role" showOptional>
                    <LemonInput placeholder="my-role" />
                </LemonField>
            </>
        )
    },
}
