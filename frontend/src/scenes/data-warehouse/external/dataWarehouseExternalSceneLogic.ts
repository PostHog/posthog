import { connect, kea, path, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, InsightShortId, ItemMode } from '~/types'

import type { dataWarehouseExternalSceneLogicType } from './dataWarehouseExternalSceneLogicType'

export const dataWarehouseExternalSceneLogic = kea<dataWarehouseExternalSceneLogicType>([
    path(() => ['scenes', 'data-warehouse', 'external', 'dataWarehouseExternalSceneLogic']),
    connect(() => ({
        actions: [insightSceneLogic, ['setSceneState']],
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
    urlToAction({
        '/data-warehouse': () => {
            insightSceneLogic.actions.setSceneState(String('new') as InsightShortId, ItemMode.Edit, undefined)
        },
    }),
])
