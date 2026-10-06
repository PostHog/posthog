import { dayjs } from 'lib/dayjs'

import { BatchExportInterval } from '~/types'

import { compareBatchExportScheduleStatus, getBatchExportScheduleStatus, lastCompleteDataInterval } from './utils'

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

    // `now` is a Wednesday at 14:37 UTC. The SQL editor previews a HogQL export over this interval.
    it.each<[BatchExportInterval, string, number | null, number | null, string, string]>([
        ['hour', 'UTC', null, null, '2026-09-30T13:00:00.000Z', '2026-09-30T14:00:00.000Z'],
        ['every 5 minutes', 'UTC', null, null, '2026-09-30T14:30:00.000Z', '2026-09-30T14:35:00.000Z'],
        ['every 15 minutes', 'UTC', null, null, '2026-09-30T14:15:00.000Z', '2026-09-30T14:30:00.000Z'],
        ['day', 'UTC', null, 0, '2026-09-29T00:00:00.000Z', '2026-09-30T00:00:00.000Z'],
        ['day', 'America/New_York', null, 3, '2026-09-29T07:00:00.000Z', '2026-09-30T07:00:00.000Z'],
        ['day', 'UTC', null, 23, '2026-09-28T23:00:00.000Z', '2026-09-29T23:00:00.000Z'],
        ['week', 'UTC', 1, 5, '2026-09-21T05:00:00.000Z', '2026-09-28T05:00:00.000Z'],
        ['week', 'UTC', 5, 0, '2026-09-18T00:00:00.000Z', '2026-09-25T00:00:00.000Z'],
    ])(
        'finds the last complete %s interval in %s with day offset %s and hour offset %s',
        (interval, timezone, offsetDay, offsetHour, expectedStart, expectedEnd) => {
            const { start, end } = lastCompleteDataInterval({
                interval,
                now: dayjs('2026-09-30T14:37:12Z'),
                timezone,
                offsetDay,
                offsetHour,
            })

            expect([start.toISOString(), end.toISOString()]).toEqual([expectedStart, expectedEnd])
        }
    )
})
