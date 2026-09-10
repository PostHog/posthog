import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { featurePreviewGateSettlingLogic } from './featurePreviewGateSettlingLogic'

describe('featurePreviewGateSettlingLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('settles on startSettling and stops when the server catches up', async () => {
        const logic = featurePreviewGateSettlingLogic({ flag: 'flag-a' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.startSettling()
        }).toMatchValues({ settling: true })

        await expectLogic(logic, () => {
            logic.actions.markServerCaughtUp()
        }).toMatchValues({ settling: false })

        // The early stop disposes the timeout, so no late timer can flip the state again.
        jest.runAllTimers()
        expect(logic.values.settling).toBe(false)
    })

    it('stops settling on its own past the timeout, so a slow pipeline cannot lock the gate', async () => {
        const logic = featurePreviewGateSettlingLogic({ flag: 'flag-b' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.startSettling()
        }).toMatchValues({ settling: true })

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(15000)
        }).toMatchValues({ settling: false })
    })

    it('does not settle while nothing was started', () => {
        const logic = featurePreviewGateSettlingLogic({ flag: 'flag-c' })
        logic.mount()
        expect(logic.values.settling).toBe(false)
    })
})
