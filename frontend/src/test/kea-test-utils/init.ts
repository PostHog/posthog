import { BuiltLogic, Logic, LogicWrapper } from 'kea'
import { initKea } from '~/initKea'
import { testUtilsPlugin } from '~/test/kea-test-utils/plugin'

export function initKeaTestLogic<L extends Logic = Logic>({
    logic,
    props,
    onLogic,
}: {
    logic: LogicWrapper<L>
    props?: LogicWrapper<L>['props']
    onLogic?: (l: BuiltLogic<L>) => any
}): void {
    let builtLogic: BuiltLogic<L>
    let unmount: () => void

    beforeEach(async () => {
        initKea({ beforePlugins: [testUtilsPlugin] })
        builtLogic = logic.build(props)
        await onLogic?.(builtLogic)
        unmount = builtLogic.mount()
    })

    afterEach(() => {
        unmount()
    })
}
