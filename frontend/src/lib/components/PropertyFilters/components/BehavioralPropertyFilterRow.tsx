import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { BehavioralEventType, BehavioralPropertyFilter, PropertyOperator, TimeUnitType } from '~/types'

import { PropertyFilterButton } from './PropertyFilterButton'

export interface BehavioralPropertyFilterRowProps {
    filter: BehavioralPropertyFilter
    onChange: (filter: BehavioralPropertyFilter) => void
    editable: boolean
    size?: 'xsmall' | 'small' | 'medium'
}

const COUNT_OPERATOR_OPTIONS = [
    { value: PropertyOperator.GreaterThanOrEqual, label: 'at least' },
    { value: PropertyOperator.LessThanOrEqual, label: 'at most' },
    { value: PropertyOperator.Exact, label: 'exactly' },
]

const TIME_INTERVAL_OPTIONS = [
    { value: TimeUnitType.Day, label: 'days' },
    { value: TimeUnitType.Week, label: 'weeks' },
    { value: TimeUnitType.Month, label: 'months' },
    { value: TimeUnitType.Year, label: 'years' },
]

export function BehavioralPropertyFilterRow({
    filter,
    onChange,
    editable,
    size = 'medium',
}: BehavioralPropertyFilterRowProps): JSX.Element {
    // Filters created via the API with explicit date bounds have no window controls to map onto
    if (!editable || filter.explicit_datetime) {
        return <PropertyFilterButton item={filter} />
    }

    const countOperator = filter.operator ?? PropertyOperator.GreaterThanOrEqual
    const countValue = filter.operator_value ?? 1

    const setCount = (operator: PropertyOperator, operatorValue: number): void => {
        // "at least once" is the plain performed_event criterion; anything else needs a count
        if (operator === PropertyOperator.GreaterThanOrEqual && operatorValue === 1) {
            onChange({
                ...filter,
                value: BehavioralEventType.PerformEvent,
                operator: undefined,
                operator_value: undefined,
            })
        } else {
            onChange({
                ...filter,
                value: BehavioralEventType.PerformMultipleEvents,
                operator,
                operator_value: operatorValue,
            })
        }
    }

    return (
        <div className="flex min-w-0 grow" data-attr="behavioral-property-filter-row">
            <div className="flex min-w-0 grow flex-wrap items-center gap-x-1 gap-y-2">
                <div className="flex w-full min-w-0 flex-wrap items-center gap-2">
                    <LemonSelect
                        size={size}
                        value={!!filter.negation}
                        onChange={(negation) =>
                            // "Did not perform" means not at all, so a count no longer applies
                            onChange(
                                negation
                                    ? {
                                          ...filter,
                                          negation: true,
                                          value: BehavioralEventType.PerformEvent,
                                          operator: undefined,
                                          operator_value: undefined,
                                      }
                                    : { ...filter, negation: undefined }
                            )
                        }
                        options={[
                            { value: false, label: 'Performed' },
                            { value: true, label: 'Did not perform' },
                        ]}
                        data-attr="behavioral-filter-negation"
                    />
                    <div className="min-w-32 flex-1">
                        <TaxonomicPopover
                            size={size}
                            groupType={TaxonomicFilterGroupType.Events}
                            groupTypes={[TaxonomicFilterGroupType.Events]}
                            value={filter.key}
                            onChange={(value) => onChange({ ...filter, key: String(value), event_type: 'events' })}
                            placeholder="Select an event"
                            fullWidth
                            truncate
                            data-attr="behavioral-filter-event"
                        />
                    </div>
                </div>
                {!filter.negation && (
                    <div className="flex items-center gap-2">
                        <LemonSelect
                            size={size}
                            value={countOperator}
                            onChange={(operator) => setCount(operator, countValue)}
                            options={COUNT_OPERATOR_OPTIONS}
                            data-attr="behavioral-filter-count-operator"
                        />
                        <LemonInput
                            type="number"
                            size={size}
                            min={1}
                            className="w-14"
                            value={countValue}
                            onChange={(operatorValue) => setCount(countOperator, operatorValue ?? 1)}
                            data-attr="behavioral-filter-count-value"
                        />
                        <span className="whitespace-nowrap">{countValue === 1 ? 'time' : 'times'}</span>
                    </div>
                )}
                <div className="flex items-center gap-2">
                    <span className="whitespace-nowrap">in the last</span>
                    <LemonInput
                        type="number"
                        size={size}
                        min={1}
                        className="w-14"
                        value={filter.time_value ?? 30}
                        onChange={(timeValue) => onChange({ ...filter, time_value: timeValue ?? 30 })}
                        data-attr="behavioral-filter-time-value"
                    />
                    <LemonSelect
                        size={size}
                        value={filter.time_interval ?? TimeUnitType.Day}
                        onChange={(timeInterval) => onChange({ ...filter, time_interval: timeInterval })}
                        options={TIME_INTERVAL_OPTIONS}
                        data-attr="behavioral-filter-time-interval"
                    />
                </div>
            </div>
        </div>
    )
}
