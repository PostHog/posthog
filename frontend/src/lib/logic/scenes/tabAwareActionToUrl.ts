import { BuiltLogic, Logic } from 'kea'
import { actionToUrl, combineUrl, router } from 'kea-router'
import { ActionToUrlPayload } from 'kea-router/lib/types'

import { sceneLogic } from 'scenes/sceneLogic'

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
                        if (sceneLogic.values.activeTabId === logic.props.tabId) {
                            const response = v(payload)
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
