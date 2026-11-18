import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import { marketingRetentionLogic } from './marketingRetentionLogic'

it('follows the dashboard date range', async () => {
    initKeaTests()
    const logic = marketingRetentionLogic()
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    marketingAnalyticsLogic.actions.setDates('-14d', null)
    expect(logic.values.query.dateRange).toEqual({ date_from: '-14d', date_to: null })
    marketingAnalyticsLogic.actions.setDates('2026-08-01', '2026-08-31')
    expect(logic.values.query.dateRange).toEqual({ date_from: '2026-08-01', date_to: '2026-08-31' })
    logic.unmount()
})

it.each([
    ['-90d', null, false],
    ['2026-06-01', '2026-08-30', false],
    ['-180d', null, true],
    ['all', null, true],
    ['2026-01-01', '2026-06-30', true],
])('flags an acquisition period the backend rejects (%s to %s)', (dateFrom, dateTo, tooLong) => {
    initKeaTests()
    const logic = marketingRetentionLogic()
    logic.mount()
    marketingAnalyticsLogic.actions.setDates(dateFrom, dateTo)
    expect(logic.values.acquisitionPeriodTooLong).toBe(tooLong)
    logic.unmount()
})
