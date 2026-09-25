import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

export const databricksDefinition: WarehouseDestinationDefinition = {
    type: 'Databricks',
    integrationKinds: ['databricks'],
    defaults: () => ({
        catalog: 'main',
        schema: 'default',
        volume: 'posthog_warehouse_sync',
        // Prefill the fixed part of the path so only the warehouse id has to be pasted.
        http_path: '/sql/1.0/warehouses/',
    }),
    requiredFields: () => ['http_path', 'catalog', 'schema', 'volume'],
    configKeys: ['http_path', 'catalog', 'schema', 'volume'],
    retargetingKeys: ['catalog', 'schema'],
    Fields: function DatabricksFields({ isNew }) {
        return (
            <>
                <LemonField
                    name="http_path"
                    label="HTTP path"
                    info="The HTTP path of your SQL warehouse or all-purpose compute, from its connection details."
                >
                    <LemonInput placeholder="/sql/1.0/warehouses/abc123" data-attr="warehouse-destination-http-path" />
                </LemonField>
                <div className="flex gap-2">
                    <LemonField name="catalog" label="Catalog" className="flex-1">
                        <LemonInput placeholder="main" disabled={!isNew} data-attr="warehouse-destination-catalog" />
                    </LemonField>
                    <LemonField name="schema" label="Schema" className="flex-1">
                        <LemonInput placeholder="default" disabled={!isNew} data-attr="warehouse-destination-schema" />
                    </LemonField>
                </div>
                <LemonField
                    name="volume"
                    label="Volume"
                    info="Unity Catalog volume used to stage files before they are loaded. It is created if it does not exist."
                >
                    <LemonInput placeholder="posthog_warehouse_sync" data-attr="warehouse-destination-volume" />
                </LemonField>
            </>
        )
    },
}
