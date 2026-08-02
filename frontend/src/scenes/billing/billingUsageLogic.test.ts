import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { billingUsageLogic } from './billingUsageLogic'

describe('billingUsageLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/billing/usage/': { status: 'ok', type: 'timeseries', customer_id: 'x', results: [] },
            },
        })
        initKeaTests()
    })

    // Presets like "This month"/"This year"/"All time" only have a start value, so the
    // picker applies them with dateTo=null. The dateTo reducer used to fall back to the
    // previous (or default) value whenever the new value was falsy, silently turning that
    // null back into a stale absolute date — which broke the picker's own preset matching
    // and made its label fall back to the "no override" placeholder.
    it('keeps dateTo unset when a date range is applied with no upper bound', () => {
        const logic = billingUsageLogic({ dashboardItemId: 'test-null-date-to' })
        logic.mount()

        logic.actions.setDateRange('2026-06-01', '2026-06-10', false)
        expect(logic.values.dateTo).toEqual('2026-06-10')

        logic.actions.setDateRange('mStart', null, false)
        expect(logic.values.dateTo).toBeNull()

        logic.unmount()
    })
})
