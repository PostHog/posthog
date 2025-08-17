import { connect, kea, path, selectors } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { SidePanelSceneContext } from '../types'
import { SIDE_PANEL_CONTEXT_KEY } from '../types'
import type { sidePanelContextLogicType } from './sidePanelContextLogicType'

export const activityFiltersForScene = (sceneConfig: SceneConfig | null): SidePanelSceneContext | null => {
    if (sceneConfig?.activityScope) {
        // NOTE: - HACKY, we are just parsing the item_id from the url optimistically...
        const pathParts = removeProjectIdIfPresent(router.values.currentLocation.pathname).split('/')
        const item_id = pathParts[2]

        // Loose check for the item_id being a number, a short_id (8 chars) or a uuid
        if (item_id && (item_id.length === 8 || item_id.length === 36 || !isNaN(parseInt(item_id)))) {
            return { activity_scope: sceneConfig.activityScope, activity_item_id: item_id }
        }

        return { activity_scope: sceneConfig.activityScope }
    }
    return null
}

export const sidePanelContextLogic = kea<sidePanelContextLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelContextLogic']),
    connect(() => ({
        values: [sceneLogic, ['sceneConfig']],
    })),

    selectors({
        sceneSidePanelContext: [
            (s) => [
                s.sceneConfig,
                // Similar to "breadcrumbs"
                (state, props) => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    if (activeSceneLogic && SIDE_PANEL_CONTEXT_KEY in activeSceneLogic.selectors) {
                        const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                        return activeSceneLogic.selectors[SIDE_PANEL_CONTEXT_KEY](
                            state,
                            activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || props
                        )
                    }
                    return null
                },
            ],
            (sceneConfig, context): SidePanelSceneContext => {
                return {
                    ...context,
                    ...(!context?.activity_scope ? activityFiltersForScene(sceneConfig) : {}),
                }
            },
            { equalityCheck: objectsEqual },
        ],
    }),
])
