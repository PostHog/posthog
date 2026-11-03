import { IconClock } from '@posthog/icons'

import { IntervalType } from '~/types'

import { FilterBarOptionControl } from './FilterBarOptionControl'

const INTERVAL_LABELS: Partial<Record<IntervalType, string>> = {
    minute: 'Minute',
    hour: 'Hour',
    day: 'Day',
    week: 'Week',
    month: 'Month',
}

export interface FilterBarIntervalProps {
    value: IntervalType | null | undefined
    onChange: (interval: IntervalType | null) => void
    intervals?: IntervalType[]
    defaultLabel?: string
    label?: string
}

export function FilterBarInterval({
    value,
    onChange,
    intervals = ['hour', 'day', 'week', 'month'],
    defaultLabel = 'Default',
    label = 'Grouped by',
}: FilterBarIntervalProps): JSX.Element | null {
    return (
        <FilterBarOptionControl
            id="interval"
            label={label}
            icon={IconClock}
            value={value ?? null}
            options={intervals.map((interval) => ({ value: interval, label: INTERVAL_LABELS[interval] ?? interval }))}
            onChange={(next) => onChange(next as IntervalType | null)}
            defaultLabel={defaultLabel}
            data-attr="filter-bar-interval"
        />
    )
}
