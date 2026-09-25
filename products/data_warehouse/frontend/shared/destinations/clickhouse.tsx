import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

export const clickhouseDefinition: WarehouseDestinationDefinition = {
    type: 'ClickHouse',
    integrationKinds: ['clickhouse'],
    defaults: () => ({ database: 'default' }),
    requiredFields: () => ['database'],
    configKeys: ['database'],
    retargetingKeys: ['database'],
    Fields: function ClickHouseFields({ isNew }) {
        return (
            <LemonField
                name="database"
                label="Database"
                info="Created if it doesn't exist."
                help="A table with a primary key can hold more than one row per key until ClickHouse merges it. Add FINAL to a query to see one row per key."
            >
                <LemonInput placeholder="default" disabled={!isNew} data-attr="warehouse-destination-database" />
            </LemonField>
        )
    },
}
