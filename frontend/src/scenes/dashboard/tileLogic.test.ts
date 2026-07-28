import { initKeaTests } from '~/test/init'

import { tileLogic } from './tileLogic'

describe('tileLogic', () => {
    let logic: ReturnType<typeof tileLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = tileLogic({ dashboardId: 1, tileId: 2, filtersOverrides: { date_from: '-7d' } })
        logic.mount()
    })

    it('stores interval and breakdown overrides on top of the initial ones', () => {
        logic.actions.setInterval('week')
        logic.actions.setBreakdown({ breakdown: '$browser', breakdown_type: 'event' })

        expect(logic.values.overrides).toEqual({
            date_from: '-7d',
            interval: 'week',
            breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
        })
    })

    it('removes the key when an override is cleared, rather than persisting null', () => {
        logic.actions.setInterval('week')
        logic.actions.setBreakdown({ breakdown: '$browser', breakdown_type: 'event' })

        logic.actions.setInterval(null)
        logic.actions.setBreakdown(null)

        expect(logic.values.overrides).toEqual({ date_from: '-7d' })
    })

    it('resetOverrides wipes every override', () => {
        logic.actions.setInterval('day')
        logic.actions.setBreakdown({ breakdown: '$browser', breakdown_type: 'event' })

        logic.actions.resetOverrides()

        expect(logic.values.overrides).toEqual({})
    })
})
