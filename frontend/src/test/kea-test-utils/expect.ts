import { BuiltLogic, LogicWrapper } from 'kea'
import { AsyncOperation, ExpectLogicMethods } from '~/test/kea-test-utils/types'
import { toDispatchActions } from '~/test/kea-test-utils/functions'
import { toMatchValues } from '~/test/kea-test-utils/functions/toMatchValues'
import { testUtilsContext } from '~/test/kea-test-utils/plugin'

async function runAsyncCode(asyncOperations: AsyncOperation[]): Promise<void> {
    for (const { logic, operation, payload } of asyncOperations) {
        if (operation === 'toDispatchActions') {
            toDispatchActions?.common?.(logic, payload)
            await toDispatchActions.async?.(logic, payload)
        } else if (operation === 'toMatchValues') {
            toMatchValues.common?.(logic, payload)
            await toMatchValues.async?.(logic, payload)
        }
    }
}

export function expectLogic<L extends BuiltLogic | LogicWrapper>(
    logic: L,
    runner?: (logic: L) => void | Promise<void>
): ExpectLogicMethods {
    const { ranActions } = testUtilsContext()
    ranActions.delete(logic)

    function syncInit(): void | Promise<void> {
        if (runner) {
            const response = runner(logic)
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
        return {
            toDispatchActions: (actions) => {
                if (asyncMode) {
                    asyncOperations.push({ operation: 'toDispatchActions', logic, payload: actions })
                } else {
                    toDispatchActions?.common?.(logic, actions)
                    const response = toDispatchActions?.sync?.(logic, actions)
                    if (response) {
                        asyncMode = true
                        asyncOperations.push(...response)
                    }
                }
                return makeExpectLogicMethods()
            },
            toMatchValues: (values) => {
                if (asyncMode) {
                    asyncOperations.push({ operation: 'toMatchValues', logic, payload: values })
                } else {
                    toMatchValues?.common?.(logic, values)
                    const response = toMatchValues?.sync?.(logic, values)
                    if (response) {
                        asyncMode = true
                        asyncOperations.push(...response)
                    }
                }
                return makeExpectLogicMethods()
            },
            then: async (callback) => {
                if (asyncMode) {
                    await runAsyncCode(asyncOperations)
                }
                await callback?.(null)
            },
        }
    }

    return makeExpectLogicMethods()
}
