import { LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

export const snowflakeDefinition: DestinationDefinition = {
    type: 'Snowflake',
    defaults: () => ({
        authentication_type: 'password',
    }),
    requiredFields: ({ isNew, formValues }) => [
        'account',
        'database',
        'warehouse',
        ...(isNew ? ['user'] : []),
        ...(isNew && formValues.authentication_type == 'password' ? ['password'] : []),
        ...(isNew && formValues.authentication_type == 'keypair' ? ['private_key'] : []),
        'schema',
        'table_name',
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
        return (
            <>
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

                <LemonField name="database" label="Database">
                    <LemonInput placeholder="my-database" />
                </LemonField>

                <LemonField name="warehouse" label="Warehouse">
                    <LemonInput placeholder="my-warehouse" />
                </LemonField>

                <LemonField name="schema" label="Schema">
                    <LemonInput placeholder="my-schema" />
                </LemonField>

                <LemonField name="table_name" label="Table name">
                    <LemonInput placeholder="events" />
                </LemonField>

                <LemonField name="role" label="Role" showOptional>
                    <LemonInput placeholder="my-role" />
                </LemonField>
            </>
        )
    },
}
