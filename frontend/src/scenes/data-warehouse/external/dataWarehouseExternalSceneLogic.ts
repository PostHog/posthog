import { kea } from 'kea'

import type { dataWarehouseExternalSceneLogicType } from './dataWarehouseExternalSceneLogicType'

export const dataWarehouseExternalSceneLogic = kea<dataWarehouseExternalSceneLogicType>({
    path: ['scenes', 'data-warehouse', 'external', 'dataWarehouseExternalSceneLogic'],
})
