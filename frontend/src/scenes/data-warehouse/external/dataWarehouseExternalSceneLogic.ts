import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataVisualizationNode, NodeKind } from '~/queries/schema'
import { Breadcrumb, InsightShortId, ItemMode } from '~/types'

import type { dataWarehouseExternalSceneLogicType } from './dataWarehouseExternalSceneLogicType'

export const DATAWAREHOUSE_EDITOR_ITEM_ID = 'new-SQL'

export const dataWarehouseExternalSceneLogic = kea<dataWarehouseExternalSceneLogicType>([
    path(() => ['scenes', 'data-warehouse', 'external', 'dataWarehouseExternalSceneLogic']),
    connect(() => ({
        values: [databaseTableListLogic, ['viewsMapById', 'database', 'databaseLoading']],
        actions: [
            insightSceneLogic,
            ['setSceneState'],
            databaseTableListLogic,
            ['loadDatabase', 'loadDatabaseSuccess'],
        ],
        logic: [
            insightDataLogic({
                dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
                cachedInsight: null,
            }),
        ],
    })),
    actions({
        loadView: (id: string) => ({ id }),
        setViewLoading: (viewLoading: boolean) => ({ viewLoading }),
    }),
    selectors(() => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.DataWarehouse,
                    name: 'Explore',
                    path: urls.dataWarehouse(),
                },
            ],
        ],
    })),
    reducers({
        viewLoading: [
            false,
            {
                loadView: () => true,
                setViewLoading: (_, { viewLoading }) => viewLoading,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        loadDatabaseSuccess: () => {
            if (router.values.currentLocation.pathname.includes('/data-warehouse/view')) {
                router.actions.push(router.values.currentLocation.pathname)
            }
        },
        loadView: async ({ id }) => {
            if (id && id in values.viewsMapById) {
                insightDataLogic
                    .findMounted({
                        dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
                        cachedInsight: null,
                    })
                    ?.actions.setQuery({
                        kind: NodeKind.DataVisualizationNode,
                        source: values.viewsMapById[id].query,
                    } as DataVisualizationNode)
            } else {
                await databaseTableListLogic.asyncActions.loadDatabase()

                if (id && id in values.viewsMapById) {
                    insightDataLogic
                        .findMounted({
                            dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
                            cachedInsight: null,
                        })
                        ?.actions.setQuery({
                            kind: NodeKind.DataVisualizationNode,
                            source: values.viewsMapById[id].query,
                        } as DataVisualizationNode)
                } else {
                    lemonToast.error('Error retrieving view')
                    router.actions.push(urls.dataWarehouse())
                }
            }

            actions.setViewLoading(false)
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse': () => {
            insightSceneLogic.actions.setSceneState(
                String('new-dataWarehouse') as InsightShortId,
                ItemMode.Edit,
                undefined
            )
        },
        '/data-warehouse/view/:id': ({ id }) => {
            insightSceneLogic.actions.setSceneState(
                String('new-dataWarehouse') as InsightShortId,
                ItemMode.Edit,
                undefined
            )
            id && actions.loadView(id)
        },
    })),
])
