import { BuiltLogic, LogicWrapper } from 'kea'
import { AsyncOperation } from '~/test/kea-test-utils/types'
import { testUtilsContext } from '~/test/kea-test-utils/plugin'
import { ExpectLogicMethods, functions } from './functions'

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
            response[functionKey as keyof Omit<ExpectLogicMethods, 'then'>] = (payload: any) => {
                if (asyncMode) {
                    asyncOperations.push({ operation: functionKey, logic, payload })
                } else {
                    common?.(logic, payload)
                    const syncResponse = sync?.(logic, payload)
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
