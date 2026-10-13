import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import {
    BEHAVIORAL_COUNT_OPERATOR_LABELS,
    behavioralEntityLabel,
    formatPropertyLabel,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { actionsModel } from '~/models/actionsModel'
import {
    AnyPropertyFilter,
    BehavioralEventType,
    BehavioralPropertyFilter,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

import { PropertyFilterButton } from './PropertyFilterButton'

export interface BehavioralPropertyFilterRowProps {
    filter: BehavioralPropertyFilter
    onChange: (filter: BehavioralPropertyFilter) => void
    editable: boolean
    /** Keys the nested event-filter editor's own propertyFilterLogic, so it must be unique per row */
    pageKey: string
    size?: 'xsmall' | 'small' | 'medium'
}

// Matches the schema: nested behavioral/cohort filters and groups are deliberately unsupported
const EVENT_FILTER_TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.Elements,
    TaxonomicFilterGroupType.HogQLExpression,
]

const COUNT_OPERATOR_OPTIONS = [
    PropertyOperator.GreaterThanOrEqual,
    PropertyOperator.LessThanOrEqual,
    PropertyOperator.Exact,
].map((value) => ({ value, label: BEHAVIORAL_COUNT_OPERATOR_LABELS[value] || 'exactly' }))

// A cleared number LemonInput reports NaN, which `??` doesn't catch
const positiveOr = (value: number | undefined, fallback: number): number =>
    typeof value === 'number' && Number.isFinite(value) && value >= 1 ? value : fallback

const TIME_INTERVAL_OPTIONS = [
    { value: TimeUnitType.Day, label: 'days' },
    { value: TimeUnitType.Week, label: 'weeks' },
    { value: TimeUnitType.Month, label: 'months' },
    { value: TimeUnitType.Year, label: 'years' },
]

export function withBehavioralCount(
    filter: BehavioralPropertyFilter,
    operator: PropertyOperator,
    operatorValue: number
): BehavioralPropertyFilter {
    // "at least once" is the plain performed_event criterion; anything else needs a count
    return operator === PropertyOperator.GreaterThanOrEqual && operatorValue === 1
        ? { ...filter, value: BehavioralEventType.PerformEvent, operator: undefined, operator_value: undefined }
        : { ...filter, value: BehavioralEventType.PerformMultipleEvents, operator, operator_value: operatorValue }
}

export function withBehavioralNegation(filter: BehavioralPropertyFilter, negation: boolean): BehavioralPropertyFilter {
    // "Did not perform" means not at all, so a count no longer applies
    return negation
        ? {
              ...filter,
              negation: true,
              value: BehavioralEventType.PerformEvent,
              operator: undefined,
              operator_value: undefined,
          }
        : { ...filter, negation: undefined }
}

export function withBehavioralEventFilters(
    filter: BehavioralPropertyFilter,
    eventFilters: AnyPropertyFilter[]
): BehavioralPropertyFilter {
    // An empty list drops the key entirely, so the stored query stays free of empty arrays
    return {
        ...filter,
        event_filters: eventFilters.length ? (eventFilters as BehavioralPropertyFilter['event_filters']) : undefined,
    }
}

export function BehavioralPropertyFilterRow({
    filter,
    onChange,
    editable,
    pageKey,
    size = 'medium',
}: BehavioralPropertyFilterRowProps): JSX.Element {
    // Only mounted for behavioral filters, so surfaces without one never pay for the actions fetch
    const { actionsById } = useValues(actionsModel)
    // Derived (not mount-time state) so a row reused for a different filter after a group deletion doesn't keep a stale open/closed state
    const [userToggledEventFilters, setUserToggledEventFilters] = useState<boolean | null>(null)
    const eventFiltersVisible = userToggledEventFilters ?? !!filter.event_filters?.length

    // Filters created via the API with explicit date bounds have no window controls to map onto
    if (!editable || filter.explicit_datetime) {
        return (
            <PropertyFilterButton item={filter}>
                {formatPropertyLabel(filter, {}, undefined, actionsById)}
            </PropertyFilterButton>
        )
    }

    const countOperator = filter.operator ?? PropertyOperator.GreaterThanOrEqual
    const countValue = filter.operator_value ?? 1

    const setCount = (operator: PropertyOperator, operatorValue: number): void => {
        posthog.capture('behavioral filter count changed', { operator, operator_value: operatorValue })
        onChange(withBehavioralCount(filter, operator, operatorValue))
    }

    return (
        <div className="flex min-w-0 grow" data-attr="behavioral-property-filter-row">
            <div className="flex min-w-0 grow flex-wrap items-center gap-x-1 gap-y-2">
                <div className="flex w-full min-w-0 flex-wrap items-center gap-2">
                    <LemonSelect
                        size={size}
                        value={!!filter.negation}
                        onChange={(negation) => {
                            posthog.capture('behavioral filter behavior changed', {
                                behavior: negation ? 'did_not_perform' : 'performed',
                            })
                            onChange(withBehavioralNegation(filter, negation))
                        }}
                        options={[
                            { value: false, label: 'Performed' },
                            { value: true, label: 'Did not perform' },
                        ]}
                        data-attr="behavioral-filter-negation"
                    />
                    <div className="flex min-w-32 flex-1 items-center gap-2">
                        <div className="min-w-0 flex-1">
                            <TaxonomicPopover
                                size={size}
                                groupType={
                                    filter.event_type === 'actions'
                                        ? TaxonomicFilterGroupType.Actions
                                        : TaxonomicFilterGroupType.Events
                                }
                                groupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                                value={filter.event_type === 'actions' ? Number(filter.key) : filter.key}
                                onChange={(value, groupType) => {
                                    const eventType =
                                        groupType === TaxonomicFilterGroupType.Actions ? 'actions' : 'events'
                                    posthog.capture('behavioral filter event or action changed', {
                                        event_type: eventType,
                                    })
                                    onChange({ ...filter, key: String(value), event_type: eventType })
                                }}
                                renderValue={() => <span>{behavioralEntityLabel(filter, actionsById)}</span>}
                                placeholder="Select an event or action"
                                fullWidth
                                truncate
                                data-attr="behavioral-filter-event"
                            />
                        </div>
                        <IconWithCount count={filter.event_filters?.length || 0} showZero={false}>
                            <LemonButton
                                icon={<IconFilter />}
                                noPadding
                                active={eventFiltersVisible}
                                onClick={() => setUserToggledEventFilters(!eventFiltersVisible)}
                                disabledReason={!filter.key ? 'Please select an event first' : undefined}
                                tooltip="Show filters"
                                data-attr="behavioral-filter-show-event-filters"
                            />
                        </IconWithCount>
                    </div>
                </div>
                {eventFiltersVisible && (
                    <div className="w-full min-w-0 pl-2" data-attr="behavioral-filter-event-filters">
                        <PropertyFilters
                            propertyFilters={filter.event_filters ?? []}
                            onChange={(eventFilters) => onChange(withBehavioralEventFilters(filter, eventFilters))}
                            pageKey={`${pageKey}-event-filters`}
                            taxonomicGroupTypes={EVENT_FILTER_TAXONOMIC_GROUP_TYPES}
                            eventNames={filter.event_type === 'events' && filter.key ? [filter.key] : []}
                            disablePopover
                            buttonSize={size}
                        />
                    </div>
                )}
                {!filter.negation && (
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
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
                            onChange={(operatorValue) => setCount(countOperator, positiveOr(operatorValue, 1))}
                            data-attr="behavioral-filter-count-value"
                        />
                        <span className="whitespace-nowrap">{countValue === 1 ? 'time' : 'times'}</span>
                    </div>
                )}
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="whitespace-nowrap">in the last</span>
                    <LemonInput
                        type="number"
                        size={size}
                        min={1}
                        className="w-14"
                        value={filter.time_value ?? 30}
                        onChange={(timeValue) => {
                            const nextTimeValue = positiveOr(timeValue, 30)
                            posthog.capture('behavioral filter time period changed', {
                                time_value: nextTimeValue,
                                time_interval: filter.time_interval ?? TimeUnitType.Day,
                            })
                            onChange({ ...filter, time_value: nextTimeValue })
                        }}
                        data-attr="behavioral-filter-time-value"
                    />
                    <LemonSelect
                        size={size}
                        value={filter.time_interval ?? TimeUnitType.Day}
                        onChange={(timeInterval) => {
                            posthog.capture('behavioral filter time period changed', {
                                time_value: filter.time_value ?? 30,
                                time_interval: timeInterval,
                            })
                            onChange({ ...filter, time_interval: timeInterval })
                        }}
                        options={TIME_INTERVAL_OPTIONS}
                        data-attr="behavioral-filter-time-interval"
                    />
                </div>
            </div>
        </div>
    )
}
