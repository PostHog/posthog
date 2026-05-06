import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { ExternalDataSourceSchema, SchemaIncrementalFieldsResponse } from '~/types'

import { sourceManagementLogic } from '../../shared/logics/sourceManagementLogic'
import type { syncMethodModalLogicType } from './syncMethodModalLogicType'

export interface SyncMethodModalLogicProps {
    schema: ExternalDataSourceSchema
}

export const syncMethodModalLogic = kea<syncMethodModalLogicType>([
    path(['products', 'dataWarehouse', 'syncMethodModalLogic']),
    props({ schema: {} } as SyncMethodModalLogicProps),
    key((props) => props.schema.id),
    connect(() => ({
        actions: [sourceManagementLogic, ['updateSchema', 'updateSchemaSuccess', 'updateSchemaFailure', 'loadSources']],
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
                    try {
                        return await api.externalDataSchemas.incremental_fields(schemaId)
                    } catch (e: any) {
                        lemonToast.error(e?.data?.message ?? e?.message ?? e)
                        throw e
                    }
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
            actions.loadSources()
            actions.resetSchemaIncrementalFields()
            actions.closeSyncMethodModal()
        },
    })),
])
