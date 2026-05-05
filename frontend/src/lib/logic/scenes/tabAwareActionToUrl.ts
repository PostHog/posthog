import { BuiltLogic, Logic } from 'kea'
import { actionToUrl, combineUrl } from 'kea-router'
import { ActionToUrlPayload } from 'kea-router/lib/types'

import { sceneLogic } from 'scenes/sceneLogic'
import type { SceneTab } from 'scenes/sceneTypes'

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
                        // Inactive tab: persist the URL the action wants into this tab's
                        // stored pathname/search/hash without touching the router. The active
                        // tab's URL (router.values.location) is irrelevant here — we need the
                        // URL the inactive logic computed for itself.
                        const response = v(payload)
                        if (!response) {
                            return undefined
                        }
                        const [nextUrl, nextSearch, nextHash] = Array.isArray(response) ? response : [response]
                        const combined = combineUrl(nextUrl, nextSearch, nextHash)
                        sceneLogic.actions.setTabs(
                            sceneLogic.values.tabs.map((tab: SceneTab) =>
                                tab.id === logic.props.tabId
                                    ? {
                                          ...tab,
                                          pathname: combined.pathname,
                                          search: combined.search,
                                          hash: combined.hash,
                                      }
                                    : tab
                            )
                        )
                        return undefined
                    }
                },
            ])
        )
        actionToUrl(newPayload)(logic)
    }
}
