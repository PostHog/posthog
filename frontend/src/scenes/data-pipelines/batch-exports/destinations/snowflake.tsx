import { LemonInput } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { PERSON_PROPERTIES_EVENT_FIELD } from './common'
import type { DestinationDefinition } from './types'

// Credentials come from a linked `snowflake` Integration, never from this destination's config.
export const snowflakeDefinition: DestinationDefinition = {
    type: 'Snowflake',
    usesIntegration: true,
    defaults: () => ({}),
    requiredFields: () => ['integration_id', 'database', 'warehouse', 'schema', 'table_name'],
    configKeys: ['database', 'warehouse', 'schema', 'table_name', 'role'],
    eventTableOverrides: {
        setName: 'people_set',
        setOnceName: 'people_set_once',
    },
    eventTableExtraFields: {
        ...PERSON_PROPERTIES_EVENT_FIELD,
        snowflake_ingested_timestamp: {
            name: 'snowflake_ingested_timestamp',
            hogql_value: 'NOW64()',
            type: 'datetime',
            schema_valid: true,
        },
    },
    Fields: function SnowflakeFields() {
        return (
            <>
                <LemonField name="integration_id" label="Connection">
                    {({ value, onChange }) => (
                        <IntegrationChoice integration="snowflake" value={value} onChange={onChange} />
                    )}
                </LemonField>

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
