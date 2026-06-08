import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

export const postgresDefinition: DestinationDefinition = {
    type: 'Postgres',
    defaults: () => ({}),
    requiredFields: ({ isNew }) => [
        ...(isNew ? ['user'] : []),
        ...(isNew ? ['password'] : []),
        'host',
        'port',
        'database',
        'schema',
        'table_name',
    ],
    eventTableOverrides: { teamIdHogql: 'toInt32(team_id)' },
    Fields: function PostgresFields({ isNew }) {
        return (
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

                <LemonField name="database" label="Database">
                    <LemonInput placeholder="my-database" />
                </LemonField>

                <LemonField name="schema" label="Schema">
                    <LemonInput placeholder="public" />
                </LemonField>

                <LemonField name="table_name" label="Table name">
                    <LemonInput placeholder="events" />
                </LemonField>

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
            </>
        )
    },
}
