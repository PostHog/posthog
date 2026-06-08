import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { DestinationDefinition } from './types'

export const postgresDefinition: DestinationDefinition = {
    type: 'Postgres',
    // Postgres can store credentials in a linked Integration (when the feature flag is on) or
    // inline in config (legacy). usesIntegration is harmless when no integration_id is set.
    usesIntegration: true,
    defaults: () => ({}),
    requiredFields: ({ isNew, featureFlags }) => {
        if (featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTGRESQL_INTEGRATION]) {
            // Only new exports must pick an integration; existing legacy exports keep their inline config.
            return [...(isNew ? ['integration_id'] : []), 'database', 'schema', 'table_name']
        }
        return [...(isNew ? ['user', 'password'] : []), 'host', 'port', 'database', 'schema', 'table_name']
    },
    eventTableOverrides: { teamIdHogql: 'toInt32(team_id)' },
    Fields: function PostgresFields({ isNew }) {
        const { featureFlags } = useValues(featureFlagLogic)
        const useIntegration = !!featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTGRESQL_INTEGRATION]

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
