import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, ExternalDataSourceSchema } from '~/types'

import { cleanSourceId } from 'products/data_warehouse/frontend/utils'

import { sourceSettingsLogic } from '../SourceScene/tabs/sourceSettingsLogic'
import type { schemaSceneLogicType } from './schemaSceneLogicType'

export const SCHEMA_SCENE_TABS = ['configuration', 'metrics'] as const
export type SchemaSceneTab = (typeof SCHEMA_SCENE_TABS)[number]

export const SCHEMA_CONFIGURATION_SECTIONS = ['details', 'sync-method', 'schedule', 'danger-zone'] as const
export type SchemaConfigurationSection = (typeof SCHEMA_CONFIGURATION_SECTIONS)[number]

export const DEFAULT_SCHEMA_SCENE_TAB: SchemaSceneTab = 'configuration'
export const DEFAULT_SCHEMA_CONFIGURATION_SECTION: SchemaConfigurationSection = 'details'

export interface SchemaSceneProps {
    sourceId: string
    schemaId: string
}

export const schemaSceneLogic = kea<schemaSceneLogicType>([
    props({} as SchemaSceneProps),
    key(({ sourceId, schemaId }) => `${sourceId}-${schemaId}`),
    path((key) => ['products', 'dataWarehouse', 'schemaSceneLogic', key]),
    connect((props: SchemaSceneProps) => ({
        values: [sourceSettingsLogic({ id: cleanSourceId(props.sourceId) }), ['source', 'sourceLoading']],
    })),
    actions({
        setCurrentTab: (tab: SchemaSceneTab) => ({ tab }),
        setCurrentSection: (section: SchemaConfigurationSection) => ({ section }),
        _setCurrentTab: (tab: SchemaSceneTab) => ({ tab }),
        _setCurrentSection: (section: SchemaConfigurationSection) => ({ section }),
    }),
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
    })),
    selectors({
        schema: [
            (s) => [s.source, (_, props) => props.schemaId],
            (source, schemaId): ExternalDataSourceSchema | null => {
                return source?.schemas.find((item) => item.id === schemaId) ?? null
            },
        ],
        breadcrumbs: [
            (s) => [s.source, s.schema, (_, props) => props.sourceId],
            (source, schema, sourceId): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Sources,
                        name: 'Sources',
                        path: urls.sources(),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataWarehouseSource,
                        name: source?.source_type || 'Source',
                        path: urls.dataWarehouseSource(sourceId, 'schemas'),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataWarehouseSourceSchema,
                        name: schema?.label ?? schema?.name ?? 'Schema',
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
        const applyTabAndSection = (tab: SchemaSceneTab, section?: SchemaConfigurationSection): void => {
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
])
