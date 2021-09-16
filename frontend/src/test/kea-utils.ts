import { Action as ReduxAction } from 'redux'
import { BuiltLogic, getContext, getPluginContext, KeaPlugin, Logic, LogicWrapper, setPluginContext } from 'kea'
import { initKea } from '~/initKea'
import { waitForAction } from 'kea-waitfor'
import { objectsEqual } from 'lib/utils'

interface CallableMethods {
    toDispatchActions: (actions: (string | ReduxAction | ((action: ReduxAction) => boolean))[]) => CallableMethods
    toMatchValues: (values: Record<string, any>) => CallableMethods
    then: Promise<void>
}

interface RecordedAction {
    action: ReduxAction
    beforeState: Record<string, any>
    afterState: Record<string, any>
}

interface PluginContext {
    recordedActions: RecordedAction[]
    pointerMap: Map<LogicWrapper | BuiltLogic, number>
}

export function initKeaTestLogic<L extends Logic = Logic>({
    logic,
    props,
    waitFor,
    onLogic,
}: {
    logic: LogicWrapper<L>
    props?: LogicWrapper<L>['props']
    waitFor?: string
    onLogic?: (l: BuiltLogic<L>) => any
}): void {
    let builtLogic: BuiltLogic<L>
    let unmount: () => void

    beforeEach(async () => {
        initKea({ beforePlugins: [testUtilsPlugin] })
        builtLogic = logic.build(props)
        await onLogic?.(builtLogic)
        unmount = builtLogic.mount()
        if (waitFor) {
            await waitForAction(builtLogic.actionTypes[waitFor])
        }
    })

    afterEach(() => {
        unmount()
    })
}

export function testUtilsContext(): PluginContext {
    return getPluginContext('testUtils') as PluginContext
}

function tryToSearchActions(
    actions: (string | ReduxAction | ((action: ReduxAction) => boolean))[],
    logic: LogicWrapper | BuiltLogic
): (string | ReduxAction | ((action: ReduxAction) => boolean))[] {
    const actionsToSearch = [...actions]
    const { recordedActions, pointerMap } = testUtilsContext()
    const actionPointer = pointerMap.get(logic) || 0

    for (let i = actionPointer; i < recordedActions.length; i++) {
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
                pointerMap.set(logic, i + 1)
                break
            }
        }
    }

    return actionsToSearch
}

export function expectLogic<L extends BuiltLogic | LogicWrapper>(
    logic: L,
    runner?: (logic: L) => void | Promise<void>
): CallableMethods {
    const { pointerMap } = testUtilsContext()

    function start(): void | Promise<void> {
        if (runner) {
            const response = runner(logic)
            if (response && typeof (response as any).then !== 'undefined') {
                return (response as any).then
            }
        }
    }

    start()

    function makeCallableMethods(): CallableMethods {
        return {
            toDispatchActions: (actions) => {
                const actionsToSearch = tryToSearchActions(actions, logic)
                if (actionsToSearch.length > 0) {
                    throw new Error(`Could not find dispatched action: ${actionsToSearch[0]}`)
                }
                return makeCallableMethods()
            },
            toMatchValues: (values) => {
                const { recordedActions } = testUtilsContext()
                const actionPointer = pointerMap.get(logic) || 0
                const currentState = recordedActions[actionPointer]?.afterState || getContext().store.getState()
                for (const [key, value] of Object.entries(values)) {
                    const currentValue = logic.selectors[key](currentState, logic.props)
                    expect(currentValue).toEqual(value)
                }

                return makeCallableMethods()
            },
            then: Promise.resolve(),
        }
    }

    return makeCallableMethods()
}

function resetTestUtilsContext(): void {
    setPluginContext('testUtils', { recordedActions: [], pointerMap: new Map() } as PluginContext)
}

export const testUtilsPlugin: () => KeaPlugin = () => ({
    name: 'testUtils',

    events: {
        afterPlugin() {
            resetTestUtilsContext()
        },

        beforeReduxStore(options) {
            options.middleware.push((store) => (next) => (action: ReduxAction) => {
                const beforeState = store.getState()
                const response = next(action)
                const afterState = store.getState()

                const { recordedActions } = testUtilsContext()
                recordedActions.push({
                    action,
                    beforeState,
                    afterState,
                })

                return response
            })
        },

        beforeCloseContext() {
            resetTestUtilsContext()
        },
    },
})
