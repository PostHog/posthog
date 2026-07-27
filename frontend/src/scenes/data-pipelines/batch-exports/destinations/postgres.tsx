import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

export const postgresDefinition: DestinationDefinition = {
    type: 'Postgres',
    // New Postgres exports must store credentials in a linked Integration. Exports created before
    // integrations existed keep their inline credentials (grandfathered), detected by integration_id.
    usesIntegration: true,
    defaults: () => ({}),
    requiredFields: ({ isNew, formValues }) => {
        if (isNew || formValues.integration_id) {
            // New exports must pick an integration; existing integration-backed exports keep theirs.
            return [...(isNew ? ['integration_id'] : []), 'database', 'schema', 'table_name']
        }
        // Legacy inline-credential exports keep their original fields when edited.
        return ['host', 'port', 'database', 'schema', 'table_name']
    },
    eventTableOverrides: { teamIdHogql: 'toInt32(team_id)' },
    Fields: function PostgresFields({ isNew, formValues }) {
        const useIntegration = isNew || !!formValues.integration_id

        return (
            <>
                {useIntegration ? (
                    <LemonField name="integration_id" label="Connection">
                        {({ value, onChange }) => (
                            <IntegrationChoice integration="postgresql" value={value} onChange={onChange} />
                        )}
                    </LemonField>
                ) : (
                    <>
                        <LemonField name="user" label="User">
                            <LemonInput placeholder={isNew ? 'my-user' : 'Leave unchanged'} />
                        </LemonField>

                        <LemonField name="password" label="Password">
                            <LemonInput placeholder={isNew ? 'my-password' : 'Leave unchanged'} type="password" />
                        </LemonField>

                        <LemonField name="host" label="Host">
                            <LemonInput placeholder="my-host" />
                        </LemonField>

                        <LemonField name="port" label="Port">
                            <LemonInput placeholder="5432" type="number" min="0" max="65535" />
                        </LemonField>
                    </>
                )}

                <LemonField name="database" label="Database">
                    <LemonInput placeholder="my-database" />
                </LemonField>

                <LemonField name="schema" label="Schema">
                    <LemonInput placeholder="public" />
                </LemonField>

                <LemonField name="table_name" label="Table name">
                    <LemonInput placeholder="events" />
                </LemonField>

                {!useIntegration && (
                    <LemonField name="has_self_signed_cert">
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                bordered
                                label={
                                    <span className="flex gap-2 items-center">
                                        Does your Postgres instance have a self-signed SSL certificate?
                                        <Tooltip title="In most cases, Heroku and RDS users should check this.">
                                            <IconInfo className="text-lg text-secondary" />
                                        </Tooltip>
                                    </span>
                                }
                                checked={!!value}
                                onChange={onChange}
                            />
                        )}
                    </LemonField>
                )}
            </>
        )
    },
}
