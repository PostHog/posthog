import { ActionToDispatch, ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'
import { tryToSearchActions } from '~/test/kea-test-utils/functions/toDispatchActionsInAnyOrder'

export const toNotHaveDispatchedActions: ExpectFunction<ActionToDispatch[]> = {
    common(logic, actions) {
        const { notFound } = tryToSearchActions(logic, actions)

        if (notFound.length !== actions.length) {
            throw new Error(`Found actions when we shouldn't have!`)
        }

        testUtilsContext().historyIndex = testUtilsContext().recordedHistory.length
        testUtilsContext().ranActions = true
    },
}
