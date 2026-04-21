import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, ExternalDataSourceSchema } from '~/types'

import { cleanSourceId } from 'products/data_warehouse/frontend/utils'

import { sourceSettingsLogic } from '../SourceScene/tabs/sourceSettingsLogic'
import type { schemaSceneLogicType } from './schemaSceneLogicType'

const SCHEMA_SCENE_TABS = ['configuration', 'metrics'] as const
export type SchemaSceneTab = (typeof SCHEMA_SCENE_TABS)[number]

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
        _setCurrentTab: (tab: SchemaSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'configuration' as SchemaSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
                _setCurrentTab: (_, { tab }) => tab,
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
            return urls.dataWarehouseSourceSchema(props.sourceId, props.schemaId, values.currentTab)
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.dataWarehouseSourceSchema(':sourceId', ':schemaId', ':tab' as any)]: (params): void => {
            const possibleTab = (params.tab ?? 'configuration') as SchemaSceneTab
            const tab = SCHEMA_SCENE_TABS.includes(possibleTab) ? possibleTab : 'configuration'
            if (tab !== values.currentTab) {
                actions._setCurrentTab(tab)
            }
        },
        [urls.dataWarehouseSourceSchema(':sourceId', ':schemaId')]: (): void => {
            if (values.currentTab !== 'configuration') {
                actions._setCurrentTab('configuration')
            }
        },
    })),
])
