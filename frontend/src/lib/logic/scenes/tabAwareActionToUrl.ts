import { BuiltLogic, Logic } from 'kea'
import { actionToUrl, combineUrl, router } from 'kea-router'
import { ActionToUrlPayload } from 'kea-router/lib/types'

import { sceneLogic } from 'scenes/sceneLogic'

import { captureRapidUrlChangeWarning, getUrlChangeTracker } from './urlChangeTracker'

function extractUrlString(response: unknown): string | null {
    if (response === undefined || response === null) {
        return null
    }
    if (typeof response === 'string') {
        return response
    }
    if (Array.isArray(response) && response.length > 0) {
        // actionToUrl returns [pathname, searchParams?, hashParams?]
        // Serialize all parts to catch [object Object] in any component
        const parts: string[] = []
        parts.push(String(response[0]))
        if (response[1] !== undefined && response[1] !== null) {
            parts.push(`?${JSON.stringify(response[1])}`)
        }
        if (response[2] !== undefined && response[2] !== null) {
            parts.push(`#${JSON.stringify(response[2])}`)
        }
        return parts.join('')
    }
    return String(response)
}

export const tabAwareActionToUrl = <L extends Logic = Logic>(
    input: ActionToUrlPayload<L> | ((logic: BuiltLogic<L>) => ActionToUrlPayload<L>)
) => {
    return (logic: BuiltLogic<L>) => {
        const finalInput = typeof input === 'function' ? input(logic) : input
        const newPayload = Object.fromEntries(
            Object.entries(finalInput).map(([actionName, v]) => [
                actionName,
                (payload: Record<string, any>): any => {
                    if (v) {
                        // Check if sceneLogic is mounted before accessing values
                        if (!sceneLogic.isMounted()) {
                            // If sceneLogic is not mounted, just execute the original action
                            return v(payload)
                        }

                        if (sceneLogic.values.activeTabId === logic.props.tabId) {
                            const response = v(payload)

                            // Track URL changes for rapid change detection
                            const urlString = extractUrlString(response)
                            if (urlString !== null) {
                                const logicPath = logic.pathString
                                const tracker = getUrlChangeTracker(logicPath)

                                // Detect [object Object] in URL - strong indicator of serialization bug
                                if (urlString.includes('[object Object]')) {
                                    // eslint-disable-next-line no-console
                                    console.error('[PostHog] Invalid URL detected - contains [object Object]', {
                                        url: urlString,
                                        action: actionName,
                                        logic: logicPath,
                                    })
                                }

                                tracker.recordChange(urlString, logicPath, actionName)

                                // Check for rapid changes and warn (no suppression)
                                if (tracker.isRapidlyChanging()) {
                                    captureRapidUrlChangeWarning(tracker, urlString, logicPath, actionName)
                                }
                            }

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
