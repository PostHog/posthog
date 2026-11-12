import { IconFilter } from '@posthog/icons'
import { Button } from '@posthog/quill'

import {
    BEHAVIORAL_COUNT_OPERATOR_OPTIONS,
    BEHAVIORAL_NEGATION_OPTIONS,
    BEHAVIORAL_TIME_INTERVAL_OPTIONS,
} from 'lib/components/PropertyFilters/utils'

import { BehavioralPropertyFilter, PropertyOperator, TimeUnitType } from '~/types'

import { QuillBehavioralNumberInput } from './QuillBehavioralNumberInput'
import { QuillFilterRowSelect } from './QuillFilterRowSelect'

export interface QuillBehavioralPropertyFilterRowProps {
    filter: BehavioralPropertyFilter
    countOperator: PropertyOperator
    countValue: number
    eventPicker: React.ReactNode
    eventFilters: React.ReactNode
    eventFiltersVisible: boolean
    onNegationChange: (negation: boolean) => void
    onCountOperatorChange: (operator: PropertyOperator) => void
    onCountValueChange: (operatorValue: number) => void
    onTimeValueChange: (timeValue: number) => void
    onTimeIntervalChange: (timeInterval: TimeUnitType) => void
    onToggleEventFilters: () => void
}

const NEGATION_OPTIONS = BEHAVIORAL_NEGATION_OPTIONS.map(({ value, label }) => ({ value: String(value), label }))

export function QuillBehavioralPropertyFilterRow({
    filter,
    countOperator,
    countValue,
    eventPicker,
    eventFilters,
    eventFiltersVisible,
    onNegationChange,
    onCountOperatorChange,
    onCountValueChange,
    onTimeValueChange,
    onTimeIntervalChange,
    onToggleEventFilters,
}: QuillBehavioralPropertyFilterRowProps): JSX.Element {
    const eventFilterCount = filter.event_filters?.length || 0
    const eventFiltersLabel = eventFilterCount ? `Show filters (${eventFilterCount})` : 'Show filters'

    return (
        <div className="flex min-w-0 grow" data-attr="behavioral-property-filter-row">
            <div className="flex min-w-0 grow flex-wrap items-center gap-x-1 gap-y-2">
                <div className="flex w-full min-w-0 flex-wrap items-center gap-2">
                    <QuillFilterRowSelect
                        value={String(!!filter.negation)}
                        options={NEGATION_OPTIONS}
                        onChange={(negation) => onNegationChange(negation === 'true')}
                        data-attr="behavioral-filter-negation"
                    />
                    <div className="flex min-w-32 flex-1 items-center gap-2">
                        <div className="min-w-0 flex-1">{eventPicker}</div>
                        <Button
                            size="icon"
                            indicator={eventFilterCount > 0 ? 'default' : undefined}
                            aria-label={eventFiltersLabel}
                            tooltip={eventFiltersLabel}
                            aria-expanded={eventFiltersVisible}
                            disabledReason={!filter.key ? 'Please select an event first' : undefined}
                            onClick={onToggleEventFilters}
                            data-attr="behavioral-filter-show-event-filters"
                        >
                            <IconFilter />
                        </Button>
                    </div>
                </div>
                {eventFilters}
                {!filter.negation && (
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <QuillFilterRowSelect
                            value={countOperator}
                            options={BEHAVIORAL_COUNT_OPERATOR_OPTIONS}
                            onChange={onCountOperatorChange}
                            data-attr="behavioral-filter-count-operator"
                        />
                        <QuillBehavioralNumberInput
                            value={countValue}
                            onChange={onCountValueChange}
                            aria-label="Number of times"
                            data-attr="behavioral-filter-count-value"
                        />
                        <span className="whitespace-nowrap">{countValue === 1 ? 'time' : 'times'}</span>
                    </div>
                )}
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="whitespace-nowrap">in the last</span>
                    <QuillBehavioralNumberInput
                        value={filter.time_value ?? 30}
                        onChange={onTimeValueChange}
                        aria-label="Time period"
                        data-attr="behavioral-filter-time-value"
                    />
                    <QuillFilterRowSelect
                        value={filter.time_interval ?? TimeUnitType.Day}
                        options={BEHAVIORAL_TIME_INTERVAL_OPTIONS}
                        onChange={onTimeIntervalChange}
                        data-attr="behavioral-filter-time-interval"
                    />
                </div>
            </div>
        </div>
    )
}
