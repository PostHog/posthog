import { BuiltLogic, Logic, LogicWrapper } from 'kea'
import { initKea } from '~/initKea'
import { testUtilsPlugin, expectLogic } from 'kea-test-utils'
import { createMemoryHistory } from 'history'
import posthog from 'posthog-js'

export function initKeaTestLogic<L extends Logic = Logic>({
    logic,
    props,
    onLogic,
}: {
    logic?: LogicWrapper<L>
    props?: LogicWrapper<L>['props']
    onLogic?: (l: BuiltLogic<L>) => any
} = {}): void {
    let builtLogic: BuiltLogic<L>
    let unmount: () => void

    beforeEach(async () => {
        posthog.init('no token', {
            api_host: 'borked',
            test: true,
            autocapture: false,
            disable_session_recording: true,
            advanced_disable_decide: true,
            opt_out_capturing_by_default: true,
            loaded: (p) => {
                p.opt_out_capturing()
            },
        })

        const history = createMemoryHistory()
        ;(history as any).pushState = history.push
        ;(history as any).replaceState = history.replace
        initKea({ beforePlugins: [testUtilsPlugin], routerLocation: history.location, routerHistory: history })
        if (logic) {
            builtLogic = logic.build({ ...props })
            await onLogic?.(builtLogic)
            unmount = builtLogic.mount()
        }
    })

    afterEach(async () => {
        if (logic) {
            unmount()
            await expectLogic(logic).toFinishAllListeners()
        }
    })
}
