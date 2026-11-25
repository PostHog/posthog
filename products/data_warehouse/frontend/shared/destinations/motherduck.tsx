import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

// Mirrors the writer's identifier check for MotherDuck database names.
const DATABASE_NAME_PATTERN = /^[A-Za-z0-9_.\-$]+$/

export const motherduckDefinition: WarehouseDestinationDefinition = {
    type: 'MotherDuck',
    integrationKinds: ['motherduck'],
    defaults: () => ({ schema: 'main' }),
    requiredFields: () => ['database'],
    validate: ({ database }) => ({
        database:
            database && !DATABASE_NAME_PATTERN.test(String(database).trim())
                ? 'Use only letters, numbers, underscores, dots, hyphens and dollar signs'
                : undefined,
    }),
    configKeys: ['database', 'schema'],
    retargetingKeys: ['database', 'schema'],
    Fields: function MotherDuckFields({ isNew }) {
        return (
            <div className="flex gap-2">
                <LemonField name="database" label="Database" className="flex-1">
                    <LemonInput placeholder="my_db" disabled={!isNew} data-attr="warehouse-destination-database" />
                </LemonField>
                <LemonField
                    name="schema"
                    label="Schema"
                    className="flex-1"
                    help="PostHog creates the schema if it does not exist."
                >
                    <LemonInput placeholder="main" disabled={!isNew} data-attr="warehouse-destination-schema" />
                </LemonField>
            </div>
        )
    },
}
