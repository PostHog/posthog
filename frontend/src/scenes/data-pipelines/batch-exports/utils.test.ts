import { dayjs } from 'lib/dayjs'

import { compareBatchExportScheduleStatus, getBatchExportScheduleStatus } from './utils'

const PAST = dayjs().subtract(1, 'day').toISOString()
const FUTURE = dayjs().add(1, 'day').toISOString()

describe('batch export utils', () => {
    it.each([
        ['paused, whatever the end date', { paused: true, end_at: FUTURE }, 'paused'],
        ['unpaused and past its end date', { paused: false, end_at: PAST }, 'ended'],
        ['unpaused and before its end date', { paused: false, end_at: FUTURE }, 'active'],
        ['unpaused with no end date', { paused: false, end_at: null }, 'active'],
    ])('reads an export that is %s', (_, batchExport, expected) => {
        expect(getBatchExportScheduleStatus(batchExport)).toBe(expected)
    })

    it('sorts live exports before ended ones and paused ones last', () => {
        const ended = { paused: false, end_at: PAST }
        const active = { paused: false, end_at: null }
        const paused = { paused: true, end_at: null }

        expect([paused, ended, active].sort(compareBatchExportScheduleStatus)).toEqual([active, ended, paused])
    })
})
