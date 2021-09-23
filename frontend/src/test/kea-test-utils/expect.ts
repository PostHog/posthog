import { BuiltLogic, LogicWrapper } from 'kea'
import { AsyncOperation } from '~/test/kea-test-utils/types'
import { ExpectLogicMethods, functions } from './functions'
import { testUtilsContext } from '~/test/kea-test-utils/plugin'

function isLogicBuildOrWrapper(logic: any): logic is BuiltLogic | LogicWrapper {
    return (logic as LogicWrapper)?._isKea || (logic as BuiltLogic)?._isKeaBuild
}

export function expectLogic<L extends BuiltLogic | LogicWrapper>(
    logicOrRunner?: L | (() => void | Promise<void>),
    runner?: () => void | Promise<void>
): ExpectLogicMethods {
    // if expectValues should show next or last values
    testUtilsContext().ranActions = false

    let logicToExpect: BuiltLogic | LogicWrapper | undefined = undefined
    if (isLogicBuildOrWrapper(logicOrRunner)) {
        logicToExpect = logicOrRunner
    } else if (typeof logicOrRunner === 'function') {
        runner = logicOrRunner
    }

    function syncInit(): void | Promise<void> {
        if (runner) {
            const response = runner()
            if (response && typeof (response as any).then !== 'undefined') {
                return (response as any).then
            }
        }
    }

    // we are in async mode if the runner function returned a promise
    const initPromise = syncInit()
    let asyncMode = !!initPromise

    const asyncOperations: AsyncOperation[] = []

    function makeExpectLogicMethods(): ExpectLogicMethods {
        const response: Partial<ExpectLogicMethods> = {
            then: async (callback: any) => {
                if (asyncMode) {
                    for (const { logic: asyncLogic, operation, payload } of asyncOperations) {
                        if (operation in functions) {
                            const { common, async } = await functions[operation as keyof typeof functions]
                            common?.(asyncLogic, payload)
                            await async?.(asyncLogic, payload)
                        } else {
                            throw new Error(`Running invalid async function "${operation}"`)
                        }
                    }
                }
                await callback?.(null)
            },
        }

        for (const [functionKey, { sync, common }] of Object.entries(functions)) {
            response[functionKey as keyof Omit<ExpectLogicMethods, 'then'>] = (
                arg1: LogicWrapper | BuiltLogic | any,
                arg2?: any
            ) => {
                let functionLogic: LogicWrapper | BuiltLogic
                let payload: any

                if (isLogicBuildOrWrapper(arg1)) {
                    functionLogic = arg1
                    payload = arg2
                } else if (!logicToExpect) {
                    throw new Error(
                        `Without "logic" in "expectLogic(logic)", you must pass it to each function separately`
                    )
                } else {
                    functionLogic = logicToExpect
                    payload = arg1
                }

                if (asyncMode) {
                    asyncOperations.push({ operation: functionKey, logic: functionLogic, payload })
                } else {
                    common?.(functionLogic, payload)
                    const syncResponse = sync?.(functionLogic, payload)
                    if (syncResponse) {
                        asyncMode = true
                        asyncOperations.push(...syncResponse)
                    }
                }
                return makeExpectLogicMethods()
            }
        }

        return response as ExpectLogicMethods
    }

    return makeExpectLogicMethods()
}
