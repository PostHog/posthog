import { BuiltLogic, getContext, LogicWrapper } from 'kea'
import { AsyncOperation, CallableMethods } from '~/test/kea-test-utils/types'
import { testUtilsContext } from '~/test/kea-test-utils/plugin'
import { Action as ReduxAction } from 'redux'
import { delay, objectsEqual } from 'lib/utils'
import { waitForAction, waitForCondition } from 'kea-waitfor'

const ASYNC_ACTION_WAIT_TIMEOUT = 3000

export function expectLogic<L extends BuiltLogic | LogicWrapper>(
    logic: L,
    runner?: (logic: L) => void | Promise<void>
): CallableMethods {
    const { pointerMap } = testUtilsContext()

    function syncInit(): void | Promise<void> {
        if (runner) {
            const response = runner(logic)
            if (response && typeof (response as any).then !== 'undefined') {
                return (response as any).then
            }
        }
    }

    const initPromise = syncInit()

    // we are in async mode if the runner function returned a promise
    let asyncMode = !!initPromise
    let ranActions = false

    const asyncOperations: AsyncOperation[] = []

    async function runAsyncCode(): Promise<void> {
        for (const { logic: _logic, operation, payload } of asyncOperations) {
            if (operation === 'toDispatchActions') {
                ranActions = true
                const actions = payload as ReduxAction[]
                for (const action of actions) {
                    const [notFound] = tryToSearchActions([action], _logic)
                    if (notFound) {
                        await Promise.race([
                            delay(ASYNC_ACTION_WAIT_TIMEOUT).then(() => {
                                throw new Error(`Timed out waiting for action: ${notFound}`)
                            }),
                            typeof notFound === 'string'
                                ? waitForAction(logic.actionTypes[notFound] || notFound)
                                : typeof notFound === 'function'
                                ? waitForCondition(notFound)
                                : waitForCondition((a) => objectsEqual(a, notFound)),
                        ])
                        tryToSearchActions([action], _logic)
                    }
                }
            } else if (operation === 'toMatchValues') {
                expectValuesToMatch(ranActions, pointerMap, logic, payload)
            }
        }
    }

    function makeCallableMethods(): CallableMethods {
        return {
            toDispatchActions: (actions) => {
                if (asyncMode) {
                    asyncOperations.push({ operation: 'toDispatchActions', logic, payload: actions })
                } else {
                    ranActions = true
                    const actionsToSearch = tryToSearchActions(actions, logic)
                    if (actionsToSearch.length > 0) {
                        asyncMode = true
                        asyncOperations.push({ operation: 'toDispatchActions', logic, payload: actionsToSearch })
                    }
                }
                return makeCallableMethods()
            },
            toMatchValues: (values) => {
                if (asyncMode) {
                    asyncOperations.push({ operation: 'toMatchValues', logic, payload: values })
                } else {
                    expectValuesToMatch(ranActions, pointerMap, logic, values)
                }
                return makeCallableMethods()
            },
            then: async (callback) => {
                if (asyncMode) {
                    await runAsyncCode()
                }
                await callback?.(null)
            },
        }
    }

    return makeCallableMethods()
}

function tryToSearchActions(
    actions: (string | ReduxAction | ((action: ReduxAction) => boolean))[],
    logic: LogicWrapper | BuiltLogic
): (string | ReduxAction | ((action: ReduxAction) => boolean))[] {
    const actionsToSearch = [...actions]
    const { recordedActions, pointerMap } = testUtilsContext()
    const actionPointer = pointerMap.get(logic) || -1

    for (let i = actionPointer + 1; i < recordedActions.length; i++) {
        pointerMap.set(logic, i)
        const actionSearch = actionsToSearch[0]
        const recordedAction = recordedActions[i]
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

function expectValuesToMatch<L extends BuiltLogic | LogicWrapper>(
    ranActions: boolean,
    pointerMap: Map<LogicWrapper | BuiltLogic, number>,
    logic: L,
    values: Record<string, any>
): void {
    const { recordedActions } = testUtilsContext()
    const currentState = ranActions
        ? recordedActions[pointerMap.get(logic) || 0]?.afterState || getContext().store.getState()
        : getContext().store.getState()
    for (const [key, value] of Object.entries(values)) {
        if (!(key in logic.selectors)) {
            throw new Error(`Count not find value with key "${key}" in logic "${logic.pathString}"`)
        }
        const currentValue = logic.selectors[key](currentState, logic.props)
        expect(currentValue).toEqual(value)
    }
}
