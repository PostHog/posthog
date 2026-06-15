import { kea, path, selectors } from 'kea'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

// The Data ops scene renders only the managed-warehouse settings (see DataWarehouseScene +
// warehouseProvisioningLogic). This logic remains solely to provide the scene's
// access-control context for the side panel.
export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseSceneLogic']),
    selectors({
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                access_control_resource: 'warehouse_objects',
            }),
        ],
    }),
])
