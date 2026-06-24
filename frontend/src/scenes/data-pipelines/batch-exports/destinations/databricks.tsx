import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Link, Tooltip } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

export const databricksDefinition: DestinationDefinition = {
    type: 'Databricks',
    usesIntegration: true,
    defaults: () => ({
        use_variant_type: true,
        // prefill prefix for http path
        http_path: '/sql/1.0/warehouses/',
    }),
    requiredFields: () => ['integration_id', 'http_path', 'catalog', 'schema', 'table_name'],
    configKeys: ['http_path', 'catalog', 'schema', 'table_name', 'use_variant_type', 'use_automatic_schema_evolution'],
    eventTableExtraFields: {
        team_id: {
            name: 'team_id',
            hogql_value: 'team_id',
            type: 'integer',
            schema_valid: true,
        },
        databricks_ingested_timestamp: {
            name: 'databricks_ingested_timestamp',
            hogql_value: 'NOW64()',
            type: 'datetime',
            schema_valid: true,
        },
    },
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function DatabricksFields({ isNew }) {
        return (
            <>
                <LemonField name="integration_id" label="Integration">
                    {({ value, onChange }) => (
                        <IntegrationChoice integration="databricks" value={value} onChange={onChange} />
                    )}
                </LemonField>

                <LemonField
                    name="http_path"
                    label="HTTP Path"
                    info={<>HTTP Path value for your all-purpose compute or SQL warehouse.</>}
                >
                    <LemonInput placeholder="/sql/1.0/warehouses/my-warehouse" />
                </LemonField>

                <LemonField name="catalog" label="Catalog">
                    <LemonInput placeholder="workspace" />
                </LemonField>

                <LemonField name="schema" label="Schema">
                    <LemonInput placeholder="default" />
                </LemonField>

                <LemonField name="table_name" label="Table name">
                    <LemonInput placeholder="my-table" />
                </LemonField>

                {isNew ? (
                    <LemonField name="use_variant_type">
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                checked={!!value}
                                onChange={onChange}
                                bordered
                                label={
                                    <span className="flex gap-2 items-center">
                                        Use VARIANT type for storing JSON data
                                        <Tooltip
                                            interactive
                                            title={
                                                <>
                                                    Using VARIANT for storing JSON data is{' '}
                                                    <Link
                                                        to="https://docs.databricks.com/aws/en/semi-structured/variant"
                                                        target="_blank"
                                                    >
                                                        recommended by Databricks
                                                    </Link>{' '}
                                                    , however, the VARIANT data type is only available in Databricks
                                                    Runtime 15.3 and above. If left unchecked, JSON data will be stored
                                                    using the STRING type.
                                                    <br />
                                                    <strong>
                                                        This setting cannot be changed after the batch export is
                                                        created.
                                                    </strong>
                                                </>
                                            }
                                        >
                                            <IconInfo className="text-lg text-secondary" />
                                        </Tooltip>
                                    </span>
                                }
                            />
                        )}
                    </LemonField>
                ) : null}
            </>
        )
    },
}
