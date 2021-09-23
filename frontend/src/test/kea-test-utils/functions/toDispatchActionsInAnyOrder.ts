import { BuiltLogic, LogicWrapper } from 'kea'
import { ActionToDispatch, ExpectFunction, testUtilsContext } from '~/test/kea-test-utils'
import { delay, objectsEqual } from 'lib/utils'
import { waitForAction, waitForCondition } from 'kea-waitfor'

const ASYNC_ACTION_WAIT_TIMEOUT = 3000

export const toDispatchActionsInAnyOrder: ExpectFunction<ActionToDispatch[]> = {
    common() {
        testUtilsContext().ranActions = true
    },

    sync(logic, actions) {
        const { notFound } = tryToSearchActions(logic, actions)
        if (notFound.length > 0) {
            return [{ operation: 'toDispatchActionsInAnyOrder', logic, payload: notFound }]
        }
    },

    async async(logic, actions) {
        const { notFound } = tryToSearchActions(logic, actions)
        if (notFound.length > 0) {
            await Promise.race([
                delay(ASYNC_ACTION_WAIT_TIMEOUT).then(() => {
                    throw new Error(
                        `Timed out waiting for action: ${
                            typeof notFound === 'object' ? JSON.stringify(notFound) : notFound
                        } in logic ${logic?.pathString}`
                    )
                }),
                Promise.all(
                    notFound.map((act) =>
                        typeof act === 'string'
                            ? waitForAction(logic.actionTypes[act] || act)
                            : typeof act === 'function'
                            ? waitForCondition(act)
                            : waitForCondition((a) => objectsEqual(a, act))
                    )
                ),
            ])
            // will not get called if the timeout throws above, otherwise it was found, and update the historyIndex
            tryToSearchActions(logic, notFound)
        }
    },
}

interface NotFoundActions {
    notFound: ActionToDispatch[]
    lastIndex: number
}

function tryToSearchActions(logic: LogicWrapper | BuiltLogic, actions: ActionToDispatch[]): NotFoundActions {
    const actionsToSearch = [...actions]
    const { recordedHistory, historyIndex } = testUtilsContext()
    const actionPointer = historyIndex || -1

    const foundMap = new Map<ActionToDispatch, number>()
    const alreadyFoundAtIndex = new Set<number>()

    for (const action of actionsToSearch) {
        for (let i = actionPointer + 1; i < recordedHistory.length; i++) {
            const recordedAction = recordedHistory[i]
            if (
                (!alreadyFoundAtIndex.has(i) &&
                    typeof action === 'string' &&
                    (recordedAction.action.type === action ||
                        (logic.actionTypes[action] && recordedAction.action.type === logic.actionTypes[action]))) ||
                (typeof action === 'function' && action(recordedAction.action)) ||
                (typeof action === 'object' && objectsEqual(recordedAction.action, action))
            ) {
                foundMap.set(action, i)
                alreadyFoundAtIndex.add(i)
                break
            }
        }
    }

    const notFound = actionsToSearch.filter((a) => !foundMap.has(a))
    const lastIndex = Math.max(actionPointer, ...Array.from(foundMap.values()))
    if (notFound.length === 0 && foundMap.size > 0) {
        testUtilsContext().historyIndex = lastIndex
    }

    return { notFound, lastIndex }
}
