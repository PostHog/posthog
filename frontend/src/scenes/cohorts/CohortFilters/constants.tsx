import React from 'react'
import {
    BehavioralFilterKey,
    BehavioralFilterType,
    CohortFieldProps,
    CohortNumberFieldProps,
    CohortTaxonomicFieldProps,
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
    OperatorType,
    PropertyMathType,
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
            [OperatorType.Equals]: {
                label: 'equals',
            },
            [OperatorType.NotEquals]: {
                label: 'does not equal',
            },
            [OperatorType.Contains]: {
                label: 'contain',
            },
            [OperatorType.NotContains]: {
                label: 'does not contain',
            },
            [OperatorType.MatchesRegex]: {
                label: 'matches regex',
            },
            [OperatorType.NotMatchesRegex]: {
                label: 'does not match regex',
            },
            [OperatorType.GreaterThan]: {
                label: 'greater than',
            },
            [OperatorType.LessThan]: {
                label: 'less than',
            },
            [OperatorType.Set]: {
                label: 'is set',
            },
            [OperatorType.NotSet]: {
                label: 'is not set',
            },
            [OperatorType.NotBetween]: {
                label: 'not between',
            },
            [OperatorType.Minimum]: {
                label: 'minimum',
            },
            [OperatorType.Maximum]: {
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
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.NotPerformedEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformEvent,
        negation: true,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.PerformMultipleEvents]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformMultipleEvents,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                key: 'operator',
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                type: FilterType.NumberTicker,
            },
            {
                key: 'operator_value',
                type: FilterType.Text,
                value: 'times in the last',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.PerformSequenceEvents]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformSequenceEvents,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'followed by',
            },
            {
                key: 'seq_event',
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'within',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'seq_time_value',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                key: 'seq_time_interval',
                type: FilterType.Text,
                value: 'of the initial event',
            },
        ],
    },
    [BehavioralEventType.NotPerformSequenceEvents]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformSequenceEvents,
        negation: true,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'followed by',
            },
            {
                key: 'seq_event',
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'within',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'seq_time_value',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                key: 'seq_time_interval',
                type: FilterType.Text,
                value: 'of the initial event',
            },
        ],
    },
    [BehavioralEventType.HaveProperty]: {
        type: BehavioralFilterKey.Person,
        value: BehavioralEventType.HaveProperty,
        fields: [
            {
                key: 'key',
                type: FilterType.EventProperties,
            },
            {
                key: 'operator',
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                key: 'value',
                type: FilterType.EventPropertyValues,
            },
        ],
    },
    [BehavioralEventType.NotHaveProperty]: {
        type: BehavioralFilterKey.Person,
        value: BehavioralEventType.HaveProperty,
        negation: true,
        fields: [
            {
                key: 'key',
                type: FilterType.EventProperties,
            },
            {
                key: 'operator',
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                key: 'value',
                type: FilterType.EventPropertyValues,
            },
        ],
    },
    [BehavioralCohortType.InCohort]: {
        type: BehavioralFilterKey.Cohort,
        value: BehavioralCohortType.InCohort,
        fields: [
            { key: 'key', type: FilterType.CohortId, value: 'id', hide: true },
            {
                key: 'value',
                type: FilterType.CohortValues,
            },
        ],
    },
    [BehavioralCohortType.NotInCohort]: {
        type: BehavioralFilterKey.Cohort,
        negation: true,
        value: BehavioralCohortType.InCohort,
        fields: [
            { key: 'key', type: FilterType.CohortId, value: 'id', hide: true },
            {
                key: 'value',
                type: FilterType.CohortValues,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventFirstTime]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.PerformEventFirstTime,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventRegularly]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.PerformEventRegularly,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                key: 'operator',
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                key: 'operator_value',
                type: FilterType.NumberTicker,
            },
            {
                type: FilterType.Text,
                value: 'times per',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 1,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'period for at least',
            },
            {
                key: 'min_periods',
                type: FilterType.Number,
                value: 3,
            },
            {
                type: FilterType.Text,
                value: 'of the last',
            },
            {
                key: 'total_periods',
                type: FilterType.Number,
                value: 5,
            },
        ],
    },
    [BehavioralLifecycleType.StopPerformEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.StopPerformEvent,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'seq_time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'seq_time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'but had done it in the',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'prior to now',
            },
        ],
    },
    [BehavioralLifecycleType.StartPerformEventAgain]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.StartPerformEventAgain,
        fields: [
            {
                key: 'key',
                type: FilterType.EventsAndActions,
            },
            {
                key: 'event_type',
                type: FilterType.EventType,
                value: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                key: 'seq_time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'seq_time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'but had not done it in the',
            },
            {
                key: 'time_value',
                type: FilterType.Number,
                value: 30,
            },
            {
                key: 'time_interval',
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'prior to now',
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
        return <CohortTextField value={String(p?.value ?? '')} />
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
