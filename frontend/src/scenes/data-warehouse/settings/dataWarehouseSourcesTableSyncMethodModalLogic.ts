import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ExternalDataSourceSchema, SchemaIncrementalFieldsResponse } from '~/types'

import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'
import type { dataWarehouseSourcesTableSyncMethodModalLogicType } from './dataWarehouseSourcesTableSyncMethodModalLogicType'

export interface DataWarehouseSourcesTableSyncMethodModalLogicProps {
    schema: ExternalDataSourceSchema
}

export const dataWarehouseSourcesTableSyncMethodModalLogic = kea<dataWarehouseSourcesTableSyncMethodModalLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'DataWarehouseSourcesTableSyncMethodModalLogic']),
    props({ schema: {} } as DataWarehouseSourcesTableSyncMethodModalLogicProps),
    key((props) => props.schema.id),
    connect(() => ({
        actions: [
            dataWarehouseSettingsLogic,
            ['updateSchema', 'updateSchemaSuccess', 'updateSchemaFailure', 'loadSources'],
        ],
    })),
    actions({
        openSyncMethodModal: (schema: ExternalDataSourceSchema) => ({ schema }),
        closeSyncMethodModal: true,
    }),
    loaders({
        schemaIncrementalFields: [
            null as SchemaIncrementalFieldsResponse | null,
            {
                loadSchemaIncrementalFields: async (schemaId: string) => {
                    return await api.externalDataSchemas.incremental_fields(schemaId)
                },
                resetSchemaIncrementalFields: () => null,
            },
        ],
    }),
    reducers({
        syncMethodModalIsOpen: [
            false as boolean,
            {
                openSyncMethodModal: () => true,
                closeSyncMethodModal: () => false,
            },
        ],
        currentSyncMethodModalSchema: [
            null as ExternalDataSourceSchema | null,
            {
                openSyncMethodModal: (_, { schema }) => schema,
                closeSyncMethodModal: () => null,
            },
        ],
        saveButtonIsLoading: [
            false as boolean,
            {
                updateSchema: () => true,
                updateSchemaFailure: () => false,
                updateSchemaSuccess: () => false,
            },
        ],
    }),
    listeners(({ actions }) => ({
        updateSchemaSuccess: () => {
            actions.loadSources(null)
            actions.resetSchemaIncrementalFields()
            actions.closeSyncMethodModal()
        },
    })),
])
