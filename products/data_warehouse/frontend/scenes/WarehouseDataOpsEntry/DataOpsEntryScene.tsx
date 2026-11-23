import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { DataWarehouseScene } from '../DataOpsScene/DataWarehouseScene'
import { dataWarehouseSceneLogic } from '../DataOpsScene/dataWarehouseSceneLogic'
import { dataOpsRedirectTarget } from './dataOpsRedirect'

export const scene: SceneExport = {
    component: DataOpsEntryScene,
    logic: dataWarehouseSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
}

/** Data ops is not a page once the console is on: its tabs live in Queries, Storage and Settings. */
export function DataOpsEntryScene(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const consoleOn = !!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]

    useEffect(() => {
        if (consoleOn) {
            router.actions.replace(dataOpsRedirectTarget(router.values.searchParams))
        }
    }, [consoleOn])

    return consoleOn ? null : <DataWarehouseScene />
}
