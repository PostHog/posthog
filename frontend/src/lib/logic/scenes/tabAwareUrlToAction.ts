import { BuiltLogic, Logic } from 'kea'
import { UrlToActionPayload } from 'kea-router/lib/types'
import { sceneLogic } from 'scenes/sceneLogic'
import { urlToAction } from 'kea-router'

export const tabAwareUrlToAction = <L extends Logic = Logic>(
    input: UrlToActionPayload<L> | ((logic: BuiltLogic<L>) => UrlToActionPayload<L>)
) => {
    return (logic: BuiltLogic<L>) => {
        const finalInput = typeof input === 'function' ? input(logic) : input
        const newPayload = Object.fromEntries(
            Object.entries(finalInput).map(([k, v]) => [
                k,
                (params: any, searchParams: any, hashParams: any, payload: any, previousLocation: any): any => {
                    if (sceneLogic.values.activeTabId === logic.props.tabId) {
                        return v(params, searchParams, hashParams, payload, previousLocation)
                    }
                },
            ])
        )
        urlToAction(newPayload)(logic)
    }
}
