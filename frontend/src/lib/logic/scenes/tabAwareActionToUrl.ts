import { BuiltLogic, Logic } from 'kea'
import { actionToUrl } from 'kea-router'
import { ActionToUrlPayload } from 'kea-router/lib/types'

export const tabAwareActionToUrl = <L extends Logic = Logic>(
    input: ActionToUrlPayload<L> | ((logic: BuiltLogic<L>) => ActionToUrlPayload<L>)
): ((logic: BuiltLogic<L>) => void) => {
    return actionToUrl<L>(input)
}
