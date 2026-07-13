import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

export const bigqueryDefinition: DestinationDefinition = {
    type: 'BigQuery',
    usesIntegration: true,
    defaults: () => ({}),
    requiredFields: () => ['integration_id', 'dataset_id', 'table_id'],
    // Credentials and project_id now live on the integration; json_config_file is a removed legacy field.
    configKeys: ['dataset_id', 'table_id', 'use_json_type'],
    eventTableOverrides: { teamIdHogql: 'team_id' },
    eventTableExtraFields: {
        bq_ingested_timestamp: {
            name: 'bq_ingested_timestamp',
            hogql_value: 'NOW64()',
            type: 'datetime',
            schema_valid: true,
        },
    },
    Fields: function BigQueryFields({ isNew }) {
        return (
            <>
                <LemonField name="integration_id" label="Integration">
                    {({ value, onChange }) => (
                        <IntegrationChoice
                            integration="google-cloud-service-account"
                            value={value}
                            onChange={onChange}
                        />
                    )}
                </LemonField>

                <LemonField name="table_id" label="Table ID">
                    <LemonInput placeholder="events" />
                </LemonField>

                <LemonField name="dataset_id" label="Dataset ID">
                    <LemonInput placeholder="dataset" />
                </LemonField>

                {isNew ? (
                    <LemonField name="use_json_type" label="Structured fields data type">
                        <LemonCheckbox
                            bordered
                            label={
                                <span className="flex gap-2 items-center">
                                    Export 'properties', 'set', and 'set_once' fields as BigQuery JSON type
                                    <Tooltip title="If left unchecked, these fields will be sent as STRING type. This setting cannot be changed after batch export is created.">
                                        <IconInfo className="text-lg text-secondary" />
                                    </Tooltip>
                                </span>
                            }
                        />
                    </LemonField>
                ) : null}
            </>
        )
    },
}
