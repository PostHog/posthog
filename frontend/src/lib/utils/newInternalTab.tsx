import { getContext } from 'kea'
import { router } from 'kea-router'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

export function newInternalTab(path?: string, source: 'internal_link' | 'unknown' = 'internal_link'): void {
    const store = getContext().store
    // sceneLogic registers its reducer at this path on mount, and is the sole listener for
    // NEW_INTERNAL_TAB. If it isn't mounted (e.g. embedded views, certain modal contexts) the
    // dispatch below would be a silent no-op — fall back to a direct router push so the navigation
    // still happens instead of swallowing the click.
    const isSceneLogicMounted = !!store.getState()?.scenes?.sceneLogic

    if (isSceneLogicMounted) {
        store.dispatch({
            type: NEW_INTERNAL_TAB,
            payload: { path, source },
        })
        return
    }

    if (path) {
        router.actions.push(path)
    }
}
