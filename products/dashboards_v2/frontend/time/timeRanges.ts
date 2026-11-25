import { type DateTimeRange, type DateTimeValue, CUSTOM_RANGE } from '@posthog/quill'

import { type Dayjs, dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { RELATIVE_TIME } from '../dashboard/dashboardSchema'
import type { TimeRange } from '../dashboard/dashboardTypes'

/** A preset the picker offers, which runs from `from` to now, such as `{ label: 'Last hour', from: 'now-1h' }`. */
export interface QuickRange {
    label: string
    from: string
}

export const DEFAULT_QUICK_RANGES: QuickRange[] = [
    { label: 'Last 24 hours', from: 'now-24h' },
    { label: 'Last 7 days', from: 'now-7d' },
    { label: 'Last 14 days', from: 'now-14d' },
    { label: 'Last 30 days', from: 'now-30d' },
    { label: 'Last 90 days', from: 'now-90d' },
]

// Dashboards and the query batch API write minutes as `m` and months as `M`. PostHog's date helpers swap them.
const POSTHOG_UNIT: Record<string, string> = { m: 'M', M: 'm' }

/** A point of a saved range as a date, resolved the way the backend resolves it. The schema rejects any other form. */
function resolve(point: string): Dayjs {
    const match = RELATIVE_TIME.exec(point)
    const relative = match ? dateStringToDayJs(`-${match[1]}${POSTHOG_UNIT[match[2]] ?? match[2]}`) : null
    return relative ?? (point === 'now' ? dayjs() : dayjs(point))
}

/** The presets as quill's picker takes them. Ids start at 1, because 0 is the picker's custom range. */
export function pickerRanges(quick: QuickRange[]): DateTimeRange[] {
    return quick.map(({ label, from }, index) => ({
        id: index + 1,
        name: label,
        rangeSetter: () => resolve(from).toDate(),
    }))
}

export function toPickerValue(time: TimeRange, quick: QuickRange[]): DateTimeValue {
    const index = time.to === 'now' ? quick.findIndex((range) => range.from === time.from) : -1
    return {
        start: resolve(time.from).toDate(),
        end: resolve(time.to).toDate(),
        range: index >= 0 ? pickerRanges(quick)[index] : CUSTOM_RANGE,
    }
}

export function fromPickerValue(value: DateTimeValue, quick: QuickRange[]): TimeRange {
    const preset = quick[value.range.id - 1]
    return preset && value.range.id !== CUSTOM_RANGE.id
        ? { from: preset.from, to: 'now' }
        : { from: value.start.toISOString(), to: value.end.toISOString() }
}

export function describeTimeRange(time: TimeRange, quick: QuickRange[]): string {
    const preset = time.to === 'now' ? quick.find((range) => range.from === time.from) : undefined
    if (preset) {
        return preset.label
    }
    return `${resolve(time.from).format('MMM D')} – ${resolve(time.to).format('MMM D')}`
}
