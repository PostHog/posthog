import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

// Redshift speaks the Postgres wire protocol and its writer subclasses the Postgres one, so it
// takes the same two config fields. Kept as its own definition rather than sharing Postgres's,
// because the two pick credentials from different integration kinds.
export const redshiftDefinition: WarehouseDestinationDefinition = {
    type: 'Redshift',
    integrationKinds: ['aws-redshift'],
    defaults: () => ({ database: 'dev', schema: 'public' }),
    requiredFields: () => ['database', 'schema'],
    configKeys: ['database', 'schema'],
    retargetingKeys: ['database', 'schema'],
    Fields: function RedshiftFields({ isNew }) {
        return (
            <div className="flex gap-2">
                <LemonField name="database" label="Database" className="flex-1">
                    <LemonInput placeholder="dev" disabled={!isNew} data-attr="warehouse-destination-database" />
                </LemonField>
                <LemonField name="schema" label="Schema" className="flex-1">
                    <LemonInput placeholder="public" disabled={!isNew} data-attr="warehouse-destination-schema" />
                </LemonField>
            </div>
        )
    },
}
