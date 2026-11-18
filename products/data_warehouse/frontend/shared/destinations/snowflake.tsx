import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

export const snowflakeDefinition: WarehouseDestinationDefinition = {
    type: 'Snowflake',
    integrationKinds: ['snowflake'],
    defaults: () => ({ schema: 'PUBLIC' }),
    // The writer asserts database, schema and warehouse are safe identifiers and fails the run
    // without them. Role is optional: Snowflake falls back to the user's default role.
    requiredFields: () => ['database', 'schema', 'warehouse'],
    configKeys: ['database', 'schema', 'warehouse', 'role'],
    retargetingKeys: ['database', 'schema'],
    Fields: function SnowflakeFields({ isNew }) {
        return (
            <>
                <div className="flex gap-2">
                    <LemonField name="database" label="Database" className="flex-1">
                        <LemonInput
                            placeholder="MY_DATABASE"
                            disabled={!isNew}
                            data-attr="warehouse-destination-database"
                        />
                    </LemonField>
                    <LemonField name="schema" label="Schema" className="flex-1">
                        <LemonInput placeholder="PUBLIC" disabled={!isNew} data-attr="warehouse-destination-schema" />
                    </LemonField>
                </div>
                <div className="flex gap-2">
                    <LemonField name="warehouse" label="Warehouse" className="flex-1">
                        <LemonInput placeholder="COMPUTE_WH" data-attr="warehouse-destination-warehouse" />
                    </LemonField>
                    <LemonField name="role" label="Role" className="flex-1" showOptional>
                        <LemonInput placeholder="Your default role" data-attr="warehouse-destination-role" />
                    </LemonField>
                </div>
            </>
        )
    },
}
