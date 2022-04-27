import React from 'react'
import {
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
            [BehavioralEventType.PerformMultipleEvents]: {
                label: 'Completed an event multiple times',
            },
            [BehavioralEventType.PerformSequenceEvents]: {
                label: 'Completed a sequence of events',
            },
            [BehavioralEventType.NotPerformedEvent]: {
                label: 'Did not complete event',
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
        type: BehavioralEventType.PerformEvent,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.NotPerformedEvent]: {
        type: BehavioralEventType.NotPerformedEvent,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.PerformMultipleEvents]: {
        type: BehavioralEventType.PerformMultipleEvents,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                type: FilterType.NumberTicker,
            },
            {
                type: FilterType.Text,
                value: 'times in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.PerformSequenceEvents]: {
        type: BehavioralEventType.PerformSequenceEvents,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'followed by',
            },
            {
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
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'of the initial event',
            },
        ],
    },
    [BehavioralEventType.HaveProperty]: {
        type: BehavioralEventType.HaveProperty,
        fields: [
            {
                type: FilterType.EventProperties,
            },
            {
                type: FilterType.Text,
                value: 'with the',
            },
            {
                type: FilterType.Value,
                value: ValueOptionType.MostRecent,
            },
            {
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                type: FilterType.EventPropertyValues,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralEventType.NotHaveProperty]: {
        type: BehavioralEventType.NotHaveProperty,
        fields: [
            {
                type: FilterType.EventProperties,
            },
            {
                type: FilterType.Text,
                value: 'with the',
            },
            {
                type: FilterType.Value,
                value: ValueOptionType.MostRecent,
            },
            {
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                type: FilterType.EventPropertyValues,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralCohortType.InCohort]: {
        type: BehavioralCohortType.InCohort,
        fields: [
            {
                type: FilterType.CohortValues,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralCohortType.NotInCohort]: {
        type: BehavioralCohortType.NotInCohort,
        fields: [
            {
                type: FilterType.CohortValues,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventFirstTime]: {
        type: BehavioralLifecycleType.PerformEventFirstTime,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventRegularly]: {
        type: BehavioralLifecycleType.PerformEventRegularly,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.MathOperator,
                value: OperatorType.Equals,
            },
            {
                type: FilterType.NumberTicker,
            },
            {
                type: FilterType.Text,
                value: 'times per',
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralLifecycleType.StopPerformEvent]: {
        type: BehavioralLifecycleType.StopPerformEvent,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'but not in the previous',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
        ],
    },
    [BehavioralLifecycleType.StartPerformEventAgain]: {
        type: BehavioralLifecycleType.StartPerformEventAgain,
        fields: [
            {
                type: FilterType.EventsAndActions,
            },
            {
                type: FilterType.Text,
                value: 'in the last',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
            },
            {
                type: FilterType.Text,
                value: 'but not in the previous',
            },
            {
                type: FilterType.Number,
                value: 30,
            },
            {
                type: FilterType.TimeUnit,
                value: TimeUnitType.Day,
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
    [FilterType.CohortValues]: function _renderField() {
        return <span>TODO</span>
    },
}
