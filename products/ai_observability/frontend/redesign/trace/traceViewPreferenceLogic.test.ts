import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { traceViewPreferenceLogic } from './traceViewPreferenceLogic'
import { TraceViewChoice } from './types'

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN

describe('traceViewPreferenceLogic', () => {
    let logic: ReturnType<typeof traceViewPreferenceLogic.build>

    function mountWithFlag(enabled: boolean): void {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: enabled })
        logic = traceViewPreferenceLogic()
        logic.mount()
    }

    beforeEach(() => {
        localStorage.clear()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each<{ flag: boolean; switches: TraceViewChoice[]; activeView: TraceViewChoice; isSwitchAvailable: boolean }>([
        { flag: true, switches: [], activeView: 'new', isSwitchAvailable: true },
        { flag: true, switches: ['legacy'], activeView: 'legacy', isSwitchAvailable: true },
        { flag: true, switches: ['legacy', 'new'], activeView: 'new', isSwitchAvailable: true },
        { flag: false, switches: [], activeView: 'legacy', isSwitchAvailable: false },
    ])(
        'shows the $activeView view when the flag is $flag after switches $switches',
        ({ flag, switches, activeView, isSwitchAvailable }) => {
            mountWithFlag(flag)
            switches.forEach((view) => logic.actions.switchView(view))
            expectLogic(logic).toMatchValues({ activeView, isSwitchAvailable })
        }
    )

    it('keeps the chosen view after a reload', () => {
        mountWithFlag(true)
        logic.actions.switchView('legacy')

        logic.unmount()
        mountWithFlag(true)
        expectLogic(logic).toMatchValues({ activeView: 'legacy' })
    })

    it('reports each switch with the view it switched to', () => {
        const capture = jest.spyOn(posthog, 'capture')
        mountWithFlag(true)
        logic.actions.switchView('legacy')
        expect(capture).toHaveBeenCalledWith('llma trace view switched', { to: 'legacy' })
    })
})
