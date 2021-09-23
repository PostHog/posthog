import { BuiltLogic, LogicWrapper } from 'kea'
import { ActionToDispatch, ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'
import { delay, objectsEqual } from 'lib/utils'
import { waitForAction, waitForCondition } from 'kea-waitfor'

const ASYNC_ACTION_WAIT_TIMEOUT = 3000

export const toDispatchActions: ExpectFunction<ActionToDispatch[]> = {
    common() {
        testUtilsContext().ranActions = true
    },

    sync(logic, actions) {
        const actionsRemaining = tryToSearchActions(logic, actions)
        if (actionsRemaining.length > 0) {
            return [{ operation: 'toDispatchActions', logic, payload: actionsRemaining }]
        }
    },

    async async(logic, actions) {
        for (const action of actions) {
            const [notFound] = tryToSearchActions(logic, [action])
            if (notFound) {
                await Promise.race([
                    delay(ASYNC_ACTION_WAIT_TIMEOUT).then(() => {
                        throw new Error(`Timed out waiting for action: ${notFound} in logic ${logic?.pathString}`)
                    }),
                    typeof notFound === 'string'
                        ? waitForAction(logic.actionTypes[notFound] || notFound)
                        : typeof notFound === 'function'
                        ? waitForCondition(notFound)
                        : waitForCondition((a) => objectsEqual(a, notFound)),
                ])
                // will not get called if the timeout throws above, otherwise it was found, and update the historyIndex
                tryToSearchActions(logic, [action])
            }
        }
    },
}

function tryToSearchActions(logic: LogicWrapper | BuiltLogic, actions: ActionToDispatch[]): ActionToDispatch[] {
    const actionsToSearch = [...actions]
    const { recordedHistory, historyIndex } = testUtilsContext()
    const actionPointer = historyIndex || -1

    for (let i = actionPointer + 1; i < recordedHistory.length; i++) {
        testUtilsContext().historyIndex = i
        const actionSearch = actionsToSearch[0]
        const recordedAction = recordedHistory[i]
        if (
            (typeof actionSearch === 'string' &&
                (recordedAction.action.type === actionSearch ||
                    (logic.actionTypes[actionSearch] &&
                        recordedAction.action.type === logic.actionTypes[actionSearch]))) ||
            (typeof actionSearch === 'function' && actionSearch(recordedAction.action)) ||
            (typeof actionSearch === 'object' && objectsEqual(recordedAction.action, actionSearch))
        ) {
            actionsToSearch.shift()
            if (actionsToSearch.length === 0) {
                break
            }
        }
    }

    return actionsToSearch
}
