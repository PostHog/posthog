import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aiObservabilitySessionsViewLogic } from './aiObservabilitySessionsViewLogic'

describe('aiObservabilitySessionsViewLogic', () => {
    let logic: ReturnType<typeof aiObservabilitySessionsViewLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = aiObservabilitySessionsViewLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // The load must be in flight first, or the `sessionsLoading` assertion passes against a value
    // that was never true and stops guarding the clause that lets the error state render at all.
    it('flags a failed sessions query and clears the flag on the next successful load', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSessions()
        }).toMatchValues({ sessionsLoading: true, sessionsError: false })

        await expectLogic(logic, () => {
            logic.actions.loadSessionsFailure()
        }).toMatchValues({ sessionsError: true, sessionsLoading: false })

        await expectLogic(logic, () => {
            logic.actions.loadSessionsSuccess([], false)
        }).toMatchValues({ sessionsError: false })
    })
})
