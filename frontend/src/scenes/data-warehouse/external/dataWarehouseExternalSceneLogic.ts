import { connect, kea, path, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, InsightShortId, ItemMode } from '~/types'

import type { dataWarehouseExternalSceneLogicType } from './dataWarehouseExternalSceneLogicType'

export const dataWarehouseExternalSceneLogic = kea<dataWarehouseExternalSceneLogicType>([
    path(() => ['scenes', 'data-warehouse', 'external', 'dataWarehouseExternalSceneLogic']),
    connect(() => ({
        actions: [
            insightSceneLogic,
            ['setSceneState'],
            insightLogic({
                dashboardItemId: 'new-SQL',
                cachedInsight: null,
            }),
            ['setInsight'],
        ],
    })),
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
    urlToAction(({ actions }) => ({
        '/sql': (_, __, { q }) => {
            insightSceneLogic.actions.setSceneState(String('new') as InsightShortId, ItemMode.Edit, undefined)
            actions.setInsight(
                {
                    ...createEmptyInsight('new', false),
                    ...(q ? { query: JSON.parse(q) } : {}),
                },
                {
                    fromPersistentApi: false,
                    overrideFilter: false,
                }
            )
        },
    })),
])
