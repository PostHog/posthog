import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    ActivityScope,
    Breadcrumb,
    ExternalDataSchemaStatus,
    ExternalDataSchemaWithSource,
    ExternalDataSource,
    ExternalDataSourceSchema,
    SchemaIncrementalFieldsResponse,
} from '~/types'

import { cleanSourceId } from 'products/data_warehouse/frontend/utils'

import type { schemaSceneLogicType } from './schemaSceneLogicType'

export const SCHEMA_SCENE_TABS = ['configuration', 'metrics', 'history'] as const
export type SchemaSceneTab = (typeof SCHEMA_SCENE_TABS)[number]

export const SCHEMA_CONFIGURATION_SECTIONS = [
    'details',
    'sync-method',
    'columns',
    'descriptions',
    'schedule',
    'danger-zone',
] as const
export type SchemaConfigurationSection = (typeof SCHEMA_CONFIGURATION_SECTIONS)[number]

export const DEFAULT_SCHEMA_SCENE_TAB: SchemaSceneTab = 'configuration'
export const DEFAULT_SCHEMA_CONFIGURATION_SECTION: SchemaConfigurationSection = 'details'

export interface SchemaSceneProps {
    sourceId: string
    schemaId: string
}

// Mirrors the bulk-update payload built by sourceSettingsLogic, but for a single schema.
function buildSchemaUpdatePayload(schema: ExternalDataSourceSchema): Partial<ExternalDataSourceSchema> {
    return {
        should_sync: schema.should_sync,
        sync_type: schema.sync_type,
        incremental_field: schema.incremental_field,
        incremental_field_type: schema.incremental_field_type,
        sync_frequency: schema.sync_frequency,
        sync_time_of_day: schema.sync_time_of_day,
        cdc_table_mode: schema.cdc_table_mode,
        enabled_columns: schema.enabled_columns ?? null,
        masked_columns: schema.masked_columns ?? null,
        row_filters: schema.row_filters ?? null,
    }
}

export const schemaSceneLogic = kea<schemaSceneLogicType>([
    props({} as SchemaSceneProps),
    // Schema ids are globally unique, so keying on schemaId alone lets the scene and ConfigurationTab
    // resolve the same instance even though they pass a differently-prefixed sourceId.
    key(({ schemaId }) => schemaId),
    path((key) => ['products', 'dataWarehouse', 'schemaSceneLogic', key]),
    actions({
        setCurrentTab: (tab: SchemaSceneTab) => ({ tab }),
        setCurrentSection: (section: SchemaConfigurationSection) => ({ section }),
        _setCurrentTab: (tab: SchemaSceneTab) => ({ tab }),
        _setCurrentSection: (section: SchemaConfigurationSection) => ({ section }),
        setIsProjectTime: (isProjectTime: boolean) => ({ isProjectTime }),
        setRefreshingSchemas: (refreshing: boolean) => ({ refreshing }),
        setResyncingSchema: (resyncing: boolean) => ({ resyncing }),
        updateSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        reloadSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        resyncSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        cancelSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        deleteTable: (schema: ExternalDataSourceSchema) => ({ schema }),
        refreshSchemas: true,
    }),
    loaders(({ props }) => ({
        schemaData: [
            null as ExternalDataSchemaWithSource | null,
            {
                loadSchema: async () => {
                    try {
                        return await api.externalDataSchemas.get(props.schemaId)
                    } catch (error: any) {
                        if (error?.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
        // Sync-method options for the schema (live call to the remote source). Kept here so the
        // sync-method section doesn't need syncMethodModalLogic, which would mount + poll the
        // full sources list via sourceManagementLogic.
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
            },
        ],
    })),
    reducers(() => ({
        currentTab: [
            DEFAULT_SCHEMA_SCENE_TAB as SchemaSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
                _setCurrentTab: (_, { tab }) => tab,
            },
        ],
        currentSection: [
            DEFAULT_SCHEMA_CONFIGURATION_SECTION as SchemaConfigurationSection,
            {
                setCurrentSection: (_, { section }) => section,
                _setCurrentSection: (_, { section }) => section,
            },
        ],
        isProjectTime: [
            false as boolean,
            {
                setIsProjectTime: (_, { isProjectTime }) => isProjectTime,
            },
        ],
        refreshingSchemas: [
            false as boolean,
            {
                setRefreshingSchemas: (_, { refreshing }) => refreshing,
                refreshSchemas: () => true,
            },
        ],
        resyncingSchema: [
            false as boolean,
            {
                resyncSchema: () => true,
                setResyncingSchema: (_, { resyncing }) => resyncing,
            },
        ],
    })),
    selectors({
        schema: [(s) => [s.schemaData], (schemaData): ExternalDataSourceSchema | null => schemaData],
        source: [
            (s) => [s.schemaData],
            // The summary carries exactly the fields the page reads (source_type, user_access_level,
            // supports_column_selection); cast to the full type so existing prop signatures are unchanged.
            (schemaData): ExternalDataSource | null =>
                (schemaData?.source ?? null) as unknown as ExternalDataSource | null,
        ],
        supportsColumnSelection: [
            (s) => [s.schemaData],
            (schemaData): boolean => !!schemaData?.source?.supports_column_selection,
        ],
        supportsRowFilters: [
            (s) => [s.schemaData],
            (schemaData): boolean => !!schemaData?.source?.supports_row_filters,
        ],
        breadcrumbs: [
            (s) => [s.schemaData, (_, props) => props.sourceId],
            (schemaData, sourceId): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Sources,
                        name: 'Sources',
                        path: urls.sources(),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataWarehouseSource,
                        name: schemaData?.source?.source_type || 'Source',
                        path: urls.dataWarehouseSource(sourceId, 'schemas'),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataWarehouseSourceSchema,
                        name: schemaData?.label ?? schemaData?.name ?? 'Schema',
                        iconType: 'data_pipeline',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [(_, props) => props, s.schema],
            (props, schema): SidePanelSceneContext | null => {
                const id = cleanSourceId(props.sourceId)
                if (!id || !schema) {
                    return null
                }
                return {
                    activity_scope: ActivityScope.EXTERNAL_DATA_SOURCE,
                    activity_item_id: id,
                    access_control_resource: 'external_data_source',
                    access_control_resource_id: id,
                }
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        updateSchema: async ({ schema }) => {
            const current = values.schemaData
            if (current) {
                actions.loadSchemaSuccess({ ...current, ...schema })
            }
            try {
                await api.externalDataSchemas.update(schema.id, buildSchemaUpdatePayload(schema))
            } catch (e: any) {
                lemonToast.error(e?.message || "Can't update schema at this time")
            } finally {
                actions.loadSchema()
            }
        },
        reloadSchema: async ({ schema }) => {
            const current = values.schemaData
            if (current) {
                actions.loadSchemaSuccess({ ...current, status: ExternalDataSchemaStatus.Running })
            }
            try {
                await api.externalDataSchemas.reload(schema.id)
                posthog.capture('schema reloaded', { sourceType: values.source?.source_type })
            } catch (e: any) {
                lemonToast.error(e?.message || 'Cant reload schema at this time')
            } finally {
                actions.loadSchema()
            }
        },
        resyncSchema: async ({ schema }) => {
            const current = values.schemaData
            if (current) {
                actions.loadSchemaSuccess({ ...current, status: ExternalDataSchemaStatus.Running })
            }
            try {
                await api.externalDataSchemas.resync(schema.id)
                posthog.capture('schema resynced', { sourceType: values.source?.source_type })
                lemonToast.success(`Resync started for ${schema.label ?? schema.name}`)
            } catch (e: any) {
                lemonToast.error(e?.message || "Couldn't start resync")
            } finally {
                actions.setResyncingSchema(false)
                actions.loadSchema()
            }
        },
        cancelSchema: async ({ schema }) => {
            try {
                await api.externalDataSchemas.cancel(schema.id)
                posthog.capture('schema sync cancelled', { sourceType: values.source?.source_type })
                lemonToast.success('Sync cancelled')
            } catch (e: any) {
                lemonToast.error(e?.message || "Can't cancel sync at this time")
            } finally {
                actions.loadSchema()
            }
        },
        deleteTable: async ({ schema }) => {
            try {
                await api.externalDataSchemas.delete_data(schema.id)
                posthog.capture('schema data deleted', { sourceType: values.source?.source_type })
                lemonToast.success(`Data for ${schema.label ?? schema.name} has been deleted`)
            } catch (e: any) {
                lemonToast.error(e?.message || "Can't delete data at this time")
            } finally {
                actions.loadSchema()
            }
        },
        refreshSchemas: async () => {
            try {
                const {
                    added = 0,
                    deleted = 0,
                    total_tables_seen = 0,
                } = await api.externalDataSources.refreshSchemas(cleanSourceId(props.sourceId))
                actions.loadSchema()
                posthog.capture('schemas refreshed', {
                    sourceType: values.source?.source_type,
                    added,
                    deleted,
                    total_tables_seen,
                })
                if (total_tables_seen === 0) {
                    const deletedSuffix =
                        deleted > 0
                            ? ` ${deleted} previously tracked table(s) were removed from the tracking list.`
                            : ''
                    lemonToast.warning(
                        `No tables found. Check the source credentials, permissions, and configuration.${deletedSuffix}`
                    )
                    return
                }
                if (added === 0 && deleted === 0) {
                    lemonToast.success(`No schema changes — all ${total_tables_seen} table(s) already tracked.`)
                    return
                }
                const counts = [added > 0 ? `${added} added` : null, deleted > 0 ? `${deleted} deleted` : null]
                    .filter(Boolean)
                    .join(' / ')
                lemonToast.success(`Schemas refreshed: ${counts}`)
            } catch (e: any) {
                lemonToast.error(e?.message || "Can't refresh schemas at this time")
            } finally {
                actions.setRefreshingSchemas(false)
            }
        },
    })),
    actionToUrl(({ props, values }) => ({
        setCurrentTab: () => {
            return urls.dataWarehouseSourceSchema(
                props.sourceId,
                props.schemaId,
                values.currentTab,
                values.currentTab === 'configuration' ? values.currentSection : undefined
            )
        },
        setCurrentSection: () => {
            return urls.dataWarehouseSourceSchema(
                props.sourceId,
                props.schemaId,
                'configuration',
                values.currentSection
            )
        },
    })),
    urlToAction(({ actions, values }) => {
        let initialNavigation = true

        const applyTabAndSection = (tab: SchemaSceneTab, section?: SchemaConfigurationSection): void => {
            if (!initialNavigation) {
                // User navigated back to this scene — refetch the schema since the page does not poll.
                actions.loadSchema()
            }
            initialNavigation = false

            if (tab !== values.currentTab) {
                actions._setCurrentTab(tab)
            }
            if (tab === 'configuration' && section && section !== values.currentSection) {
                actions._setCurrentSection(section)
            }
        }

        return {
            [urls.dataWarehouseSourceSchema(':sourceId', ':schemaId', 'configuration', ':section' as any)]: (
                params
            ): void => {
                const possibleSection = params.section as SchemaConfigurationSection
                const section = SCHEMA_CONFIGURATION_SECTIONS.includes(possibleSection)
                    ? possibleSection
                    : DEFAULT_SCHEMA_CONFIGURATION_SECTION
                applyTabAndSection('configuration', section)
            },
            [urls.dataWarehouseSourceSchema(':sourceId', ':schemaId', ':tab' as any)]: (params): void => {
                const possibleTab = (params.tab ?? DEFAULT_SCHEMA_SCENE_TAB) as SchemaSceneTab
                const tab = SCHEMA_SCENE_TABS.includes(possibleTab) ? possibleTab : DEFAULT_SCHEMA_SCENE_TAB
                applyTabAndSection(tab)
            },
            [urls.dataWarehouseSourceSchema(':sourceId', ':schemaId')]: (): void => {
                applyTabAndSection(DEFAULT_SCHEMA_SCENE_TAB, DEFAULT_SCHEMA_CONFIGURATION_SECTION)
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.loadSchema()
    }),
])
