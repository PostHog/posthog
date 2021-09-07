// Utilities for frontend logic tests
import { BuiltLogic, Logic, LogicWrapper } from 'kea'
import { initKea } from '~/initKea'
import { waitForAction } from 'kea-waitfor'

type TestLogicCallback<T> = (
    logic: T,
    utils: { waitFor: (action: any) => Promise<void> }
) => (() => void | Promise<void>)[]

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
}): (callback: TestLogicCallback<L>) => Promise<void> {
    let builtLogic: BuiltLogic<L>
    let unmount: () => void

    beforeEach(async () => {
        initKea()
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

    return (callback: TestLogicCallback<L>) => testLogic(builtLogic, callback)
}

export async function testLogic<T extends BuiltLogic>(logic: T, callback: TestLogicCallback<T>): Promise<void> {
    const operations = callback(logic, {
        waitFor: async (action: any): Promise<void> => {
            const response = await waitForAction(action)
            expect(response).toMatchSnapshot()
        },
    })
    for (const operation of operations) {
        expect(logic.values).toMatchSnapshot()
        await operation()
    }
    expect(logic.values).toMatchSnapshot()
}
