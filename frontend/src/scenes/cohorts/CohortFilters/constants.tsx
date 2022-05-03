import React from 'react'
import {
    BehavioralFilterKey,
    BehavioralFilterType,
    CohortFieldProps,
    CohortNumberFieldProps,
    CohortTaxonomicFieldProps,
    CohortTextFieldProps,
    FieldOptionsType,
    FieldValues,
    FilterType,
    Row,
} from 'scenes/cohorts/CohortFilters/types'
import {
    ActorGroupType,
    BaseMathType,
    BehavioralCohortType,
    BehavioralEventType,
    BehavioralLifecycleType,
    DateOperatorType,
    PropertyMathType,
    PropertyOperator,
    TimeUnitType,
    ValueOptionType,
} from '~/types'
import {
    CohortNumberField,
    CohortSelectorField,
    CohortTaxonomicField,
    CohortTextField,
} from 'scenes/cohorts/CohortFilters/CohortField'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { CohortTypeEnum } from 'lib/constants'

/*
 * Cohort filters are broken down into 3 layers of components.
 * Row                   (i.e. <Completed an event> <Pageview> in the last <30> <days>)
 *   -> Field            (i.e. <Pageview>)
 *     -> Field values  (i.e. <Pageview, Pageleave, Autocapture, etc.)
 */

export const FIELD_VALUES: Record<FieldOptionsType, FieldValues> = {
    [FieldOptionsType.EventAggregation]: {
        label: 'Event Aggregation',
        type: FieldOptionsType.EventAggregation,
        values: {
            [BaseMathType.Total]: {
                label: 'Total',
            },
            [BaseMathType.DailyActive]: {
                label: 'Unique',
            },
            [BaseMathType.WeeklyActive]: {
                label: 'Count of weekly active',
            },
            [BaseMathType.MonthlyActive]: {
                label: 'Count of weekly active',
            },
        },
    },
    [FieldOptionsType.PropertyAggregation]: {
        label: 'Property Aggregation',
        type: FieldOptionsType.PropertyAggregation,
        values: {
            [PropertyMathType.Average]: {
                label: 'Average',
            },
            [PropertyMathType.Sum]: {
                label: 'Sum',
            },
            [PropertyMathType.Minimum]: {
                label: 'Minimum',
            },
            [PropertyMathType.Maximum]: {
                label: 'Maximum',
            },
            [PropertyMathType.Median]: {
                label: 'Median',
            },
            [PropertyMathType.P90]: {
                label: '90th percentile',
            },
            [PropertyMathType.P95]: {
                label: '95th percentile',
            },
            [PropertyMathType.P99]: {
                label: '99th percentile',
            },
        },
    },
    [FieldOptionsType.Actors]: {
        label: 'Actors',
        type: FieldOptionsType.Actors,
        values: {
            [ActorGroupType.Person]: {
                label: 'Persons',
            },
        },
    },
    [FieldOptionsType.EventBehavioral]: {
        label: 'Behavioral',
        type: FieldOptionsType.EventBehavioral,
        values: {
            [BehavioralEventType.PerformEvent]: {
                label: 'Completed event',
            },
            [BehavioralEventType.NotPerformedEvent]: {
                label: 'Did not complete event',
            },
            [BehavioralEventType.PerformMultipleEvents]: {
                label: 'Completed an event multiple times',
            },
            [BehavioralEventType.PerformSequenceEvents]: {
                label: 'Completed a sequence of events',
            },
            [BehavioralEventType.NotPerformSequenceEvents]: {
                label: 'Did not complete a sequence of events',
            },
            [BehavioralEventType.HaveProperty]: {
                label: 'Have the property',
            },
            [BehavioralEventType.NotHaveProperty]: {
                label: 'Do not have the property',
            },
        },
    },
    [FieldOptionsType.CohortBehavioral]: {
        label: 'Cohorts',
        type: FieldOptionsType.CohortBehavioral,
        values: {
            [BehavioralCohortType.InCohort]: {
                label: 'In cohort',
            },
            [BehavioralCohortType.NotInCohort]: {
                label: 'Not in cohort',
            },
        },
    },
    [FieldOptionsType.LifecycleBehavioral]: {
        label: 'Lifecycle',
        type: FieldOptionsType.LifecycleBehavioral,
        values: {
            [BehavioralLifecycleType.PerformEventFirstTime]: {
                label: 'Completed an event for the first time',
            },
            [BehavioralLifecycleType.PerformEventRegularly]: {
                label: 'Completed an event regularly',
            },
            [BehavioralLifecycleType.StopPerformEvent]: {
                label: 'Stopped doing an event',
            },
            [BehavioralLifecycleType.StartPerformEventAgain]: {
                label: 'Started doing an event again',
            },
        },
    },
    [FieldOptionsType.TimeUnits]: {
        label: 'Units',
        type: FieldOptionsType.TimeUnits,
        values: {
            [TimeUnitType.Day]: {
                label: 'days',
            },
            [TimeUnitType.Week]: {
                label: 'weeks',
            },
            [TimeUnitType.Month]: {
                label: 'months',
            },
            [TimeUnitType.Year]: {
                label: 'years',
            },
        },
    },
    [FieldOptionsType.DateOperators]: {
        label: 'Date Operators',
        type: FieldOptionsType.DateOperators,
        values: {
            [DateOperatorType.BeforeTheLast]: {
                label: 'before the last',
            },
            [DateOperatorType.Between]: {
                label: 'between',
            },
            [DateOperatorType.NotBetween]: {
                label: 'not between',
            },
            [DateOperatorType.OnTheDate]: {
                label: 'on the date',
            },
            [DateOperatorType.NotOnTheDate]: {
                label: 'not on the date',
            },
            [DateOperatorType.Since]: {
                label: 'since',
            },
            [DateOperatorType.Before]: {
                label: 'before',
            },
            [DateOperatorType.IsSet]: {
                label: 'is set',
            },
        },
    },
    [FieldOptionsType.MathOperators]: {
        label: 'Operators',
        type: FieldOptionsType.MathOperators,
        values: {
            [PropertyOperator.Exact]: {
                label: 'equals',
            },
            [PropertyOperator.IsNot]: {
                label: 'does not equal',
            },
            [PropertyOperator.IContains]: {
                label: 'contain',
            },
            [PropertyOperator.NotIContains]: {
                label: 'does not contain',
            },
            [PropertyOperator.Regex]: {
                label: 'matches regex',
            },
            [PropertyOperator.NotRegex]: {
                label: 'does not match regex',
            },
            [PropertyOperator.GreaterThan]: {
                label: 'greater than',
            },
            [PropertyOperator.GreaterThanOrEqual]: {
                label: 'greater than or equal to',
            },
            [PropertyOperator.LessThan]: {
                label: 'less than',
            },
            [PropertyOperator.LessThanOrEqual]: {
                label: 'less than or equal to',
            },
            [PropertyOperator.IsSet]: {
                label: 'is set',
            },
            [PropertyOperator.IsNotSet]: {
                label: 'is not set',
            },
            [PropertyOperator.Between]: {
                label: 'between',
            },
            [PropertyOperator.NotBetween]: {
                label: 'not between',
            },
            [PropertyOperator.Minimum]: {
                label: 'minimum',
            },
            [PropertyOperator.Maximum]: {
                label: 'maximum',
            },
        },
    },
    [FieldOptionsType.ValueOptions]: {
        label: 'Value Options',
        type: FieldOptionsType.ValueOptions,
        values: {
            [ValueOptionType.MostRecent]: {
                label: 'most recent value',
            },
            [ValueOptionType.Previous]: {
                label: 'previous value',
            },
            [ValueOptionType.OnDate]: {
                label: 'value on the date',
            },
        },
    },
}

export const ROWS: Record<BehavioralFilterType, Row> = {
    [BehavioralEventType.PerformEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformEvent,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.NotPerformedEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformEvent,
        negation: true,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.PerformMultipleEvents]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformMultipleEvents,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                fieldKey: 'operator',
                type: FilterType.MathOperator,
                defaultValue: PropertyOperator.Exact,
            },
            {
                fieldKey: 'operator_value',
                type: FilterType.NumberTicker,
                defaultValue: 5,
            },
            {
                type: FilterType.Text,
                defaultValue: 'times in the last',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.PerformSequenceEvents]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformSequenceEvents,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'followed by',
            },
            {
                fieldKey: 'seq_event',
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                defaultValue: 'within',
            },
            {
                fieldKey: 'seq_time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'seq_time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'of the initial event',
            },
        ],
    },
    [BehavioralEventType.NotPerformSequenceEvents]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformSequenceEvents,
        negation: true,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'followed by',
            },
            {
                fieldKey: 'seq_event',
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                defaultValue: 'within',
            },
            {
                fieldKey: 'seq_time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'seq_time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'of the initial event',
            },
        ],
    },
    [BehavioralEventType.HaveProperty]: {
        type: BehavioralFilterKey.Person,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventProperties,
            },
            {
                fieldKey: 'operator',
                type: FilterType.MathOperator,
                defaultValue: PropertyOperator.Exact,
            },
            {
                fieldKey: 'value',
                type: FilterType.EventPropertyValues,
            },
        ],
    },
    [BehavioralEventType.NotHaveProperty]: {
        type: BehavioralFilterKey.Person,
        negation: true,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventProperties,
            },
            {
                fieldKey: 'operator',
                type: FilterType.MathOperator,
                defaultValue: PropertyOperator.Exact,
            },
            {
                fieldKey: 'value',
                type: FilterType.EventPropertyValues,
            },
        ],
    },
    [BehavioralCohortType.InCohort]: {
        type: BehavioralFilterKey.Cohort,
        fields: [
            { fieldKey: 'key', type: FilterType.CohortId, defaultValue: 'id', hide: true },
            {
                fieldKey: 'value',
                type: FilterType.CohortValues,
            },
        ],
    },
    [BehavioralCohortType.NotInCohort]: {
        type: BehavioralFilterKey.Cohort,
        negation: true,
        fields: [
            { fieldKey: 'key', type: FilterType.CohortId, defaultValue: 'id', hide: true },
            {
                fieldKey: 'value',
                type: FilterType.CohortValues,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventFirstTime]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.PerformEventFirstTime,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventRegularly]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.PerformEventRegularly,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                fieldKey: 'operator',
                type: FilterType.MathOperator,
                defaultValue: PropertyOperator.Exact,
            },
            {
                fieldKey: 'operator_value',
                type: FilterType.NumberTicker,
                defaultValue: 5,
            },
            {
                type: FilterType.Text,
                defaultValue: 'times per',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 1,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'period for at least',
            },
            {
                fieldKey: 'min_periods',
                type: FilterType.Number,
                defaultValue: 3,
            },
            {
                type: FilterType.Text,
                defaultValue: 'of the last',
            },
            {
                fieldKey: 'total_periods',
                type: FilterType.Number,
                defaultValue: 5,
            },
        ],
    },
    [BehavioralLifecycleType.StopPerformEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.StopPerformEvent,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'seq_time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'seq_time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'but had done it in the',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'prior to now',
            },
        ],
    },
    [BehavioralLifecycleType.StartPerformEventAgain]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.StartPerformEventAgain,
        fields: [
            {
                fieldKey: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'in the last',
            },
            {
                fieldKey: 'seq_time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'seq_time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'but had not done it in the',
            },
            {
                fieldKey: 'time_value',
                type: FilterType.Number,
                defaultValue: 30,
            },
            {
                fieldKey: 'time_interval',
                type: FilterType.TimeUnit,
                defaultValue: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                defaultValue: 'prior to now',
            },
        ],
    },
}

// Building blocks of a row
export const renderField: Record<FilterType, (props: CohortFieldProps) => JSX.Element> = {
    [FilterType.Behavioral]: function _renderField(p) {
        return (
            <CohortSelectorField
                {...p}
                fieldOptionGroupTypes={[
                    FieldOptionsType.EventBehavioral,
                    FieldOptionsType.CohortBehavioral,
                    FieldOptionsType.LifecycleBehavioral,
                ]}
            />
        )
    },
    [FilterType.Aggregation]: function _renderField(p) {
        return (
            <CohortSelectorField
                {...p}
                fieldOptionGroupTypes={[FieldOptionsType.EventAggregation, FieldOptionsType.PropertyAggregation]}
            />
        )
    },
    [FilterType.Actors]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.Actors]} />
    },
    [FilterType.TimeUnit]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.TimeUnits]} />
    },
    [FilterType.DateOperator]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.DateOperators]} />
    },
    [FilterType.MathOperator]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.MathOperators]} />
    },
    [FilterType.Value]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.ValueOptions]} />
    },
    [FilterType.Text]: function _renderField(p) {
        const _p = p as CohortTextFieldProps
        return <CohortTextField {..._p} value={String(_p?.value ?? '')} />
    },
    [FilterType.EventsAndActions]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                placeholder="Choose event or action"
            />
        )
    },
    [FilterType.EventProperties]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                placeholder="Choose event property"
            />
        )
    },
    [FilterType.EventPropertyValues]: function _renderField() {
        return <span>TODO</span>
    },
    [FilterType.Number]: function _renderField(p) {
        return <CohortNumberField {...(p as CohortNumberFieldProps)} />
    },
    [FilterType.NumberTicker]: function _renderField(p) {
        return <CohortNumberField {...(p as CohortNumberFieldProps)} />
    },
    [FilterType.CohortValues]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                placeholder="Choose cohort"
            />
        )
    },
    [FilterType.EventType]: function _renderField() {
        return <></>
    },
    [FilterType.CohortId]: function _renderField() {
        return <></>
    },
}

export const CRITERIA_VALIDATIONS = {
    [FilterType.EventsAndActions]: 'Event or action cannot be empty.',
    [FilterType.EventProperties]: 'Event property cannot be empty.',
    [FilterType.EventPropertyValues]: 'Event property value cannot be empty',
    [FilterType.EventType]: 'Event type cannot be empty.',
    [FilterType.Number]: 'Period values must be at least 1 day and cannot be empty.',
    [FilterType.NumberTicker]: 'Number cannot be empty.',
    [FilterType.TimeUnit]: 'Time interval cannot be empty.',
    [FilterType.MathOperator]: 'Math operator cannot be empty.',
    [FilterType.CohortId]: 'Cohort id cannot be empty.',
    [FilterType.CohortValues]: 'Cohort value cannot be empty.',
    [FilterType.Value]: 'Event property value selector cannot be empty.',
    [FilterType.DateOperator]: 'Date cannot be empty or invalid.',
    [FilterType.MathOperator]: 'Math operator cannot be empty.',
    [FilterType.Actors]: 'Actors selector cannot be empty.',
    [FilterType.Aggregation]: 'Aggregation selector cannot be empty.',
    [FilterType.Behavioral]: 'Behavioral selector cannot be empty.',
}

export const COHORT_TYPE_OPTIONS: LemonSelectOptions = {
    [CohortTypeEnum.Static]: {
        label: 'Static · Updated manually',
    },
    [CohortTypeEnum.Dynamic]: {
        label: 'Dynamic · Updates automatically',
    },
}
