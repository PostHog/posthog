import { initKeaTests } from '~/test/init'

import { traceViewHostLogic } from './traceViewHostLogic'

describe('traceViewHostLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('starts with the spans mode and messages tab', () => {
        const logic = traceViewHostLogic({ hostId: 'a' })
        logic.mount()

        expect(logic.values.mode).toBe('spans')
        expect(logic.values.detailTab).toBe('messages')
        expect(logic.values.requestedStepId).toBeNull()
        expect(logic.values.openingMode).toBeNull()
        expect(logic.values.seedQuery).toBe('')
    })

    it('does not share state between hosts', () => {
        const first = traceViewHostLogic({ hostId: 'first' })
        const second = traceViewHostLogic({ hostId: 'second' })
        first.mount()
        second.mount()

        first.actions.setMode('feedback')

        expect(first.values.mode).toBe('feedback')
        expect(second.values.mode).toBe('spans')
    })

    it('publishQuery changes no state', () => {
        const logic = traceViewHostLogic({ hostId: 'a' })
        logic.mount()
        const before = { ...logic.values }

        logic.actions.publishQuery('abc')

        expect(logic.values).toEqual(before)
    })
})
