import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    Breadcrumb,
    DataWarehouseSettingsTab,
    ExternalDataJob,
    ExternalDataSourceSchema,
    ExternalDataStripeSource,
} from '~/types'

import type { dataWarehouseSourceSettingsLogicType } from './dataWarehouseSourceSettingsLogicType'

export enum DataWarehouseSourceSettingsTabs {
    Schemas = 'schemas',
    Syncs = 'syncs',
}

export interface DataWarehouseSourceSettingsLogicProps {
    id: string
    parentSettingsTab: DataWarehouseSettingsTab
}

export const dataWarehouseSourceSettingsLogic = kea<dataWarehouseSourceSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'source', 'dataWarehouseSourceSettingsLogic']),
    props({} as DataWarehouseSourceSettingsLogicProps),
    key(({ id }) => id),
    actions({
        setCurrentTab: (tab: DataWarehouseSourceSettingsTabs) => ({ tab }),
        setParentSettingsTab: (tab: DataWarehouseSettingsTab) => ({ tab }),
        setSourceId: (id: string) => ({ id }),
    }),
    loaders(({ values }) => ({
        source: [
            null as ExternalDataStripeSource | null,
            {
                loadSource: async () => {
                    return await api.externalDataSources.get(values.sourceId)
                },
                updateSchema: async (schema: ExternalDataSourceSchema) => {
                    const updatedSchema = await api.externalDataSchemas.update(schema.id, schema)

                    const source = values.source
                    const schemaIndex = source?.schemas.findIndex((n) => n.id === schema.id)
                    if (schemaIndex !== undefined) {
                        source!.schemas[schemaIndex] = updatedSchema
                    }

                    return source
                },
            },
        ],
        jobs: [
            [] as ExternalDataJob[],
            {
                loadJobs: async () => {
                    return await api.externalDataSources.jobs(values.sourceId)
                },
            },
        ],
    })),
    reducers({
        currentTab: [
            DataWarehouseSourceSettingsTabs.Schemas as DataWarehouseSourceSettingsTabs,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
        parentSettingsTab: [
            DataWarehouseSettingsTab.Managed as DataWarehouseSettingsTab,
            {
                setParentSettingsTab: (_, { tab }) => tab,
            },
        ],
        sourceId: [
            '' as string,
            {
                setSourceId: (_, { id }) => id,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.parentSettingsTab, s.sourceId],
            (parentSettingsTab, sourceId): Breadcrumb[] => [
                {
                    key: Scene.DataWarehouse,
                    name: 'Data Warehouse',
                    path: urls.dataWarehouse(),
                },
                {
                    key: Scene.DataWarehouseSettings,
                    name: 'Data Warehouse Settings',
                    path: urls.dataWarehouseSettings(parentSettingsTab),
                },
                {
                    key: Scene.dataWarehouseSourceSettings,
                    name: 'Data Warehouse Source Settings',
                    path: urls.dataWarehouseSourceSettings(sourceId, parentSettingsTab),
                },
            ],
        ],
    }),
    urlToAction(({ actions, values }) => ({
        '/data-warehouse/settings/:parentTab/:id': ({ parentTab, id }) => {
            if (id) {
                actions.setSourceId(id)
            }

            if (parentTab !== values.parentSettingsTab) {
                actions.setParentSettingsTab(parentTab as DataWarehouseSettingsTab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSource()
        actions.loadJobs()
    }),
])
