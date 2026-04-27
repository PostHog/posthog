import { BuiltLogic, Logic } from 'kea'
import { urlToAction } from 'kea-router'
import { UrlToActionPayload } from 'kea-router/lib/types'

import { sceneLogic } from 'scenes/sceneLogic'

export const tabAwareUrlToAction = <L extends Logic = Logic>(
    input: UrlToActionPayload<L> | ((logic: BuiltLogic<L>) => UrlToActionPayload<L>)
) => {
    return (logic: BuiltLogic<L>) => {
        const finalInput = typeof input === 'function' ? input(logic) : input
        const newPayload = Object.fromEntries(
            Object.entries(finalInput).map(([k, v]) => [
                k,
                (params: any, searchParams: any, hashParams: any, payload: any, previousLocation: any): any => {
                    // kea-router's popListener can fire after the per-tab logic has unmounted
                    // (e.g. during a deep-link load like /sql#q=...). Dispatching an action on
                    // an unmounted logic throws "X.create is not a function".
                    if (!logic.isMounted()) {
                        return
                    }
                    // Check if sceneLogic is mounted before accessing values
                    if (!sceneLogic.isMounted()) {
                        // If sceneLogic is not mounted, just execute the original action
                        return v(params, searchParams, hashParams, payload, previousLocation)
                    }

                    if (sceneLogic.values.activeTabId === logic.props.tabId) {
                        return v(params, searchParams, hashParams, payload, previousLocation)
                    }
                },
            ])
        )
        urlToAction(newPayload)(logic)
    }
}
