import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

export const postgresDefinition: WarehouseDestinationDefinition = {
    type: 'Postgres',
    integrationKinds: ['postgresql'],
    defaults: () => ({ database: 'postgres', schema: 'public' }),
    requiredFields: () => ['database', 'schema'],
    configKeys: ['database', 'schema'],
    retargetingKeys: ['database', 'schema'],
    Fields: function PostgresFields({ isNew }) {
        return (
            <div className="flex gap-2">
                <LemonField name="database" label="Database" className="flex-1">
                    <LemonInput placeholder="postgres" disabled={!isNew} data-attr="warehouse-destination-database" />
                </LemonField>
                <LemonField name="schema" label="Schema" className="flex-1">
                    <LemonInput placeholder="public" disabled={!isNew} data-attr="warehouse-destination-schema" />
                </LemonField>
            </div>
        )
    },
}
