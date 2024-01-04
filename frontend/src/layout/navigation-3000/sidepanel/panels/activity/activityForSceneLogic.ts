import { connect, kea, path, selectors } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'kea-test-utils'
import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { ActivityScope, UserBasicType } from '~/types'

import type { activityForSceneLogicType } from './activityForSceneLogicType'

export type ActivityFilters = {
    scope?: ActivityScope
    item_id?: ActivityLogItem['item_id']
    user?: UserBasicType['id']
}

export const activityFiltersForScene = (sceneConfig: SceneConfig | null): ActivityFilters | null => {
    if (sceneConfig?.activityScope) {
        // NOTE: - HACKY, we are just parsing the item_id from the url optimistically...
        const pathParts = router.values.currentLocation.pathname.split('/')
        const item_id = pathParts[2]

        return { scope: sceneConfig.activityScope, item_id }
    }
    return null
}

export const activityForSceneLogic = kea<activityForSceneLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'activityForSceneLogic']),
    connect({
        values: [sceneLogic, ['sceneConfig']],
    }),
    selectors({
        sceneActivityFilters: [
            (s) => [
                // Similar to "breadcrumbs"
                (state, props) => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    const sceneConfig = s.sceneConfig(state, props)
                    if (activeSceneLogic && 'activityFilters' in activeSceneLogic.selectors) {
                        const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                        return activeSceneLogic.selectors.activityFilters(
                            state,
                            activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || props
                        )
                    } else {
                        return activityFiltersForScene(sceneConfig)
                    }
                },
            ],
            (filters): ActivityFilters | null => filters,
            { equalityCheck: objectsEqual },
        ],
    }),
])
