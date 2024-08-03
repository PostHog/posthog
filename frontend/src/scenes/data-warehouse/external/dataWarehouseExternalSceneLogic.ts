import { kea, path, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { dataWarehouseExternalSceneLogicType } from './dataWarehouseExternalSceneLogicType'

export const dataWarehouseExternalSceneLogic = kea<dataWarehouseExternalSceneLogicType>([
    path(() => ['scenes', 'data-warehouse', 'external', 'dataWarehouseExternalSceneLogic']),
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
])
