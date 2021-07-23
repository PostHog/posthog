// Utilities for frontend logic tests
import { BuiltLogic, Logic, LogicWrapper } from 'kea'
import { initKea } from '~/initKea'
import { waitForAction } from 'kea-waitfor'

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
}
