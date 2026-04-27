import { BuiltLogic, Logic } from 'kea'
import { actionToUrl, combineUrl, router } from 'kea-router'
import { ActionToUrlPayload } from 'kea-router/lib/types'

import { sceneLogic } from 'scenes/sceneLogic'

import { trackUrlChange } from './urlChangeTracker'

export const tabAwareActionToUrl = <L extends Logic = Logic>(
    input: ActionToUrlPayload<L> | ((logic: BuiltLogic<L>) => ActionToUrlPayload<L>)
) => {
    return (logic: BuiltLogic<L>) => {
        const finalInput = typeof input === 'function' ? input(logic) : input
        const newPayload = Object.fromEntries(
            Object.entries(finalInput).map(([k, v]) => [
                k,
                (payload: Record<string, any>): any => {
                    if (v) {
                        // kea-router can dispatch via this wrapper after the per-tab logic
                        // has unmounted; calling action creators on it would throw
                        // "X.create is not a function".
                        if (!logic.isMounted()) {
                            return undefined
                        }
                        // Check if sceneLogic is mounted before accessing values
                        if (!sceneLogic.isMounted()) {
                            // If sceneLogic is not mounted, just execute the original action
                            return v(payload)
                        }

                        if (sceneLogic.values.activeTabId === logic.props.tabId) {
                            const response = v(payload)
                            trackUrlChange(response, logic.pathString, k)
                            return response
                        }
                        // If we want to change the URL, but we're inactive, just update the tab value
                        sceneLogic.actions.setTabs(
                            sceneLogic.values.tabs.map((tab) => {
                                if (tab.id === logic.props.tabId) {
                                    const { pathname, search, hash } = router.values.location
                                    const { url } = combineUrl(pathname, search, hash)
                                    return { ...tab, url }
                                }
                                return tab
                            })
                        )
                        return undefined
                    }
                },
            ])
        )
        actionToUrl(newPayload)(logic)
    }
}
