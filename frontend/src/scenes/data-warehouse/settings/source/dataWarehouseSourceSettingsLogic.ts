import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import posthog from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    Breadcrumb,
    DataWarehouseSettingsTab,
    DataWarehouseTab,
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

const REFRESH_INTERVAL = 5000

export const dataWarehouseSourceSettingsLogic = kea<dataWarehouseSourceSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'source', 'dataWarehouseSourceSettingsLogic']),
    props({} as DataWarehouseSourceSettingsLogicProps),
    key(({ id }) => id),
    actions({
        setCurrentTab: (tab: DataWarehouseSourceSettingsTabs) => ({ tab }),
        setParentSettingsTab: (tab: DataWarehouseTab) => ({ tab }),
        setSourceId: (id: string) => ({ id }),
        reloadSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        resyncSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
    }),
    loaders(({ actions, values }) => ({
        source: [
            null as ExternalDataStripeSource | null,
            {
                loadSource: async () => {
                    return await api.externalDataSources.get(values.sourceId)
                },
                updateSchema: async (schema: ExternalDataSourceSchema) => {
                    // Optimistic UI updates before sending updates to the backend
                    const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataStripeSource
                    const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
                    clonedSource.schemas[schemaIndex] = schema
                    actions.loadSourceSuccess(clonedSource)

                    const updatedSchema = await api.externalDataSchemas.update(schema.id, schema)

                    const source = values.source
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
            DataWarehouseTab.ManagedSources as DataWarehouseTab,
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
                    path: urls.dataWarehouse(parentSettingsTab),
                },
                {
                    key: Scene.dataWarehouseSourceSettings,
                    name: 'Data Warehouse Source Settings',
                    path: urls.dataWarehouseSourceSettings(sourceId, parentSettingsTab),
                },
            ],
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        loadSourceSuccess: () => {
            clearTimeout(cache.sourceRefreshTimeout)

            cache.sourceRefreshTimeout = setTimeout(() => {
                actions.loadSource()
            }, REFRESH_INTERVAL)
        },
        loadSourceFailure: () => {
            clearTimeout(cache.sourceRefreshTimeout)

            cache.sourceRefreshTimeout = setTimeout(() => {
                actions.loadSource()
            }, REFRESH_INTERVAL)
        },
        loadJobsSuccess: () => {
            clearTimeout(cache.jobsRefreshTimeout)

            cache.jobsRefreshTimeout = setTimeout(() => {
                actions.loadJobs()
            }, REFRESH_INTERVAL)
        },
        loadJobsFailure: () => {
            clearTimeout(cache.jobsRefreshTimeout)

            cache.jobsRefreshTimeout = setTimeout(() => {
                actions.loadJobs()
            }, REFRESH_INTERVAL)
        },
        reloadSchema: async ({ schema }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataStripeSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            clonedSource.status = 'Running'
            clonedSource.schemas[schemaIndex].status = 'Running'

            actions.loadSourceSuccess(clonedSource)

            try {
                await api.externalDataSchemas.reload(schema.id)

                posthog.capture('schema reloaded', { sourceType: clonedSource.source_type })
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant reload schema at this time')
                }
            }
        },
        resyncSchema: async ({ schema }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataStripeSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            clonedSource.status = 'Running'
            clonedSource.schemas[schemaIndex].status = 'Running'

            actions.loadSourceSuccess(clonedSource)

            try {
                await api.externalDataSchemas.resync(schema.id)

                posthog.capture('schema resynced', { sourceType: clonedSource.source_type })
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant refresh schema at this time')
                }
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/data-warehouse/settings/:parentTab/:id': ({ parentTab, id }) => {
            if (id) {
                actions.setSourceId(id)
            }

            if (parentTab !== values.parentSettingsTab) {
                actions.setParentSettingsTab(parentTab as DataWarehouseTab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSource()
        actions.loadJobs()
    }),
])
