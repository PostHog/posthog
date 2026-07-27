import { BuiltLogic, Logic } from 'kea'
import { actionToUrl } from 'kea-router'
import { ActionToUrlPayload } from 'kea-router/lib/types'

import { trackUrlChange } from './urlChangeTracker'

export const trackedActionToUrl = <L extends Logic = Logic>(
    input: ActionToUrlPayload<L> | ((logic: BuiltLogic<L>) => ActionToUrlPayload<L>)
) => {
    return (logic: BuiltLogic<L>) => {
        const finalInput = typeof input === 'function' ? input(logic) : input
        const newPayload = Object.fromEntries(
            Object.entries(finalInput).map(([k, v]) => [
                k,
                (payload: Record<string, any>): any => {
                    if (v) {
                        const response = v(payload)
                        trackUrlChange(response, logic.pathString, k)
                        return response
                    }
                },
            ])
        )
        actionToUrl(newPayload)(logic)
    }
}
