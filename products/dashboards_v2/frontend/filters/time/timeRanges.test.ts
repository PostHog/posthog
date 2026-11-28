import { CUSTOM_RANGE } from '@posthog/quill'

import { type QuickRange, describeTimeRange, fromPickerValue, toPickerValue } from './timeRanges'
import { type TimeRange } from './timeRangeSchema'

const RANGES: QuickRange[] = [
    { label: 'Last hour', from: 'now-1h' },
    { label: 'Last 2 hours', from: 'now-2h' },
]
const NOW = new Date('2026-01-15T12:00:00Z')

describe('timeRanges', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(NOW)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each<{ name: string; time: TimeRange; saved: TimeRange; custom: boolean; timezone?: string }>([
        {
            name: 'a quick range stays relative',
            time: { from: 'now-2h', to: 'now' },
            saved: { from: 'now-2h', to: 'now' },
            custom: false,
        },
        {
            name: 'fixed dates stay fixed',
            time: { from: '2026-01-01T00:00:00.000Z', to: '2026-01-02T00:00:00.000Z' },
            saved: { from: '2026-01-01T00:00:00.000Z', to: '2026-01-02T00:00:00.000Z' },
            custom: true,
        },
        {
            name: 'a relative range the host does not offer becomes fixed dates, with minutes as m',
            time: { from: 'now-30m', to: 'now' },
            saved: { from: '2026-01-15T11:30:00.000Z', to: '2026-01-15T12:00:00.000Z' },
            custom: true,
        },
        {
            name: 'days count back from now, not from midnight',
            time: { from: 'now-3d', to: 'now' },
            saved: { from: '2026-01-12T12:00:00.000Z', to: '2026-01-15T12:00:00.000Z' },
            custom: true,
        },
        {
            name: 'a time without an offset is in the project timezone',
            time: { from: '2026-01-01T00:00:00', to: 'now' },
            saved: { from: '2026-01-01T05:00:00.000Z', to: '2026-01-15T12:00:00.000Z' },
            custom: true,
            timezone: 'America/New_York',
        },
    ])('$name', ({ time, saved, custom, timezone }) => {
        const value = toPickerValue(time, RANGES, timezone)

        expect(value.range.id === CUSTOM_RANGE.id).toBe(custom)
        expect(fromPickerValue(value, RANGES)).toEqual(saved)
    })

    test.each<{ name: string; time: TimeRange; label: string }>([
        { name: 'unlisted relative range', time: { from: 'now-3h', to: 'now' }, label: 'Last 3 hours' },
        {
            name: 'whole days name their last day',
            time: { from: '2026-01-05T00:00:00Z', to: '2026-01-08T00:00:00Z' },
            label: 'Jan 5 – Jan 7',
        },
        {
            name: 'hours within one day',
            time: { from: '2026-01-05T09:00:00Z', to: '2026-01-05T13:30:00Z' },
            label: 'Jan 5, 09:00 – 13:30',
        },
        {
            name: 'hours across days',
            time: { from: '2026-01-05T22:00:00Z', to: '2026-01-06T02:00:00Z' },
            label: 'Jan 5, 22:00 – Jan 6, 02:00',
        },
    ])('describes $name', ({ time, label }) => {
        expect(describeTimeRange(time, RANGES, 'UTC')).toBe(label)
    })
})
