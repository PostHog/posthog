import React from 'react'
import {
    BehavioralFilterKey,
    BehavioralFilterType,
    CohortClientErrors,
    CohortFieldProps,
    CohortNumberFieldProps,
    CohortPersonPropertiesValuesFieldProps,
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
    CohortCriteriaGroupFilter,
    CohortType,
    DateOperatorType,
    FilterLogicalOperator,
    PropertyMathType,
    PropertyOperator,
    TimeUnitType,
    ValueOptionType,
} from '~/types'
import {
    CohortNumberField,
    CohortPersonPropertiesValuesField,
    CohortSelectorField,
    CohortTaxonomicField,
    CohortTextField,
} from 'scenes/cohorts/CohortFilters/CohortField'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { CohortTypeEnum, PROPERTY_MATCH_TYPE } from 'lib/constants'

/*
 * Cohort filters are broken down into 3 layers of components.
 * Row                   (i.e. <Completed an event> <Pageview> in the last <30> <days>)
 *   -> Field            (i.e. <Pageview>)
 *     -> Field values  (i.e. <Pageview, Pageleave, Autocapture, etc.)
 */

export type FieldValuesTypes =
    | BaseMathType
    | PropertyMathType
    | ActorGroupType
    | BehavioralEventType
    | BehavioralCohortType
    | TimeUnitType
    | DateOperatorType
    | PropertyOperator
    | ValueOptionType

export const FIELD_VALUES: Record<FieldOptionsType, FieldValues> = {
    [FieldOptionsType.EventAggregation]: {
        label: 'Event Aggregation',
        type: FieldOptionsType.EventAggregation,
        values: [
            { value: BaseMathType.Total, label: 'Total' },
            { value: BaseMathType.DailyActive, label: 'Unique' },
            { value: BaseMathType.WeeklyActive, label: 'Count of weekly active' },
            { value: BaseMathType.MonthlyActive, label: 'Count of weekly active' },
        ],
    },
    [FieldOptionsType.PropertyAggregation]: {
        label: 'Property Aggregation',
        type: FieldOptionsType.PropertyAggregation,
        values: [
            { value: PropertyMathType.Average, label: 'Average' },
            { value: PropertyMathType.Sum, label: 'Sum' },
            { value: PropertyMathType.Minimum, label: 'Minimum' },
            { value: PropertyMathType.Maximum, label: 'Maximum' },
            { value: PropertyMathType.Median, label: 'Median' },
            { value: PropertyMathType.P90, label: '90th percentile' },
            { value: PropertyMathType.P95, label: '95th percentile' },
            { value: PropertyMathType.P99, label: '99th percentile' },
        ],
    },
    [FieldOptionsType.Actors]: {
        label: 'Actors',
        type: FieldOptionsType.Actors,
        values: [{ value: ActorGroupType.Person, label: 'Persons' }],
    },
    [FieldOptionsType.EventBehavioral]: {
        label: 'Behavioral',
        type: FieldOptionsType.EventBehavioral,
        values: [
            {
                value: BehavioralEventType.PerformEvent,
                label: 'Completed event',
            },
            {
                value: BehavioralEventType.NotPerformedEvent,
                label: 'Did not complete event',
            },
            {
                value: BehavioralEventType.PerformMultipleEvents,
                label: 'Completed an event multiple times',
            },
        ],
    },
    [FieldOptionsType.PersonPropertyBehavioral]: {
        label: 'Person Properties',
        type: FieldOptionsType.PersonPropertyBehavioral,
        values: [
            { value: BehavioralEventType.HaveProperty, label: 'Have the property' },
            { value: BehavioralEventType.NotHaveProperty, label: 'Do not have the property' },
        ],
    },
    [FieldOptionsType.CohortBehavioral]: {
        label: 'Cohorts',
        type: FieldOptionsType.CohortBehavioral,
        values: [
            { value: BehavioralCohortType.InCohort, label: 'In cohort' },
            { value: BehavioralCohortType.NotInCohort, label: 'Not in cohort' },
        ],
    },
    [FieldOptionsType.LifecycleBehavioral]: {
        label: 'Lifecycle',
        type: FieldOptionsType.LifecycleBehavioral,
        values: [],
    },
    [FieldOptionsType.TimeUnits]: {
        label: 'Units',
        type: FieldOptionsType.TimeUnits,
        values: [
            { value: TimeUnitType.Day, label: 'days' },
            { value: TimeUnitType.Week, label: 'weeks' },
            { value: TimeUnitType.Month, label: 'months' },
            { value: TimeUnitType.Year, label: 'years' },
        ],
    },
    [FieldOptionsType.DateOperators]: {
        label: 'Date Operators',
        type: FieldOptionsType.DateOperators,
        values: [
            { value: DateOperatorType.BeforeTheLast, label: 'before the last' },
            { value: DateOperatorType.Between, label: 'between' },
            { value: DateOperatorType.NotBetween, label: 'not between' },
            { value: DateOperatorType.OnTheDate, label: 'on the date' },
            { value: DateOperatorType.NotOnTheDate, label: 'not on the date' },
            { value: DateOperatorType.Since, label: 'since' },
            { value: DateOperatorType.Before, label: 'before' },
            { value: DateOperatorType.IsSet, label: 'is set' },
        ],
    },
    [FieldOptionsType.MathOperators]: {
        label: 'Operators',
        type: FieldOptionsType.MathOperators,
        values: [
            { value: PropertyOperator.Exact, label: 'equals' },
            { value: PropertyOperator.IsNot, label: 'does not equal' },
            { value: PropertyOperator.IContains, label: 'contain' },
            { value: PropertyOperator.NotIContains, label: 'does not contain' },
            { value: PropertyOperator.Regex, label: 'matches regex' },
            { value: PropertyOperator.NotRegex, label: 'does not match regex' },
            { value: PropertyOperator.GreaterThan, label: 'greater than' },
            { value: PropertyOperator.GreaterThanOrEqual, label: 'greater than or equal to' },
            { value: PropertyOperator.LessThan, label: 'less than' },
            { value: PropertyOperator.LessThanOrEqual, label: 'less than or equal to' },
            { value: PropertyOperator.IsSet, label: 'is set' },
            { value: PropertyOperator.IsNotSet, label: 'is not set' },
            { value: PropertyOperator.Between, label: 'between' },
            { value: PropertyOperator.NotBetween, label: 'not between' },
            { value: PropertyOperator.Minimum, label: 'minimum' },
            { value: PropertyOperator.Maximum, label: 'maximum' },
        ],
    },
    [FieldOptionsType.EventsAndActionsMathOperators]: {
        label: 'Operators',
        type: FieldOptionsType.EventsAndActionsMathOperators,
        values: [
            { value: PropertyOperator.Exact, label: 'exactly' },
            { value: PropertyOperator.GreaterThanOrEqual, label: 'at least' },
            { value: PropertyOperator.LessThanOrEqual, label: 'at most' },
        ],
    },
    [FieldOptionsType.ValueOptions]: {
        label: 'Value Options',
        type: FieldOptionsType.ValueOptions,
        values: [
            { value: ValueOptionType.MostRecent, label: 'most recent value' },
            { value: ValueOptionType.Previous, label: 'previous value' },
            { value: ValueOptionType.OnDate, label: 'value on the date' },
        ],
    },
}

export const SCALE_FIELD_VALUES = {
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
}

export const ROWS: Record<BehavioralFilterType, Row> = {
    [BehavioralEventType.PerformEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralEventType.PerformEvent,
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '30',
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
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '30',
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
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                type: FilterType.EventsAndActionsMathOperator,
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
                defaultValue: '30',
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
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '30',
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
                groupTypeFieldKey: 'seq_event_type',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'seq_event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'within',
            },
            {
                fieldKey: 'seq_time_value',
                type: FilterType.Number,
                defaultValue: '15',
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
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '30',
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
                groupTypeFieldKey: 'seq_event_type',
                type: FilterType.EventsAndActions,
            },
            {
                fieldKey: 'seq_event_type',
                type: FilterType.EventType,
                defaultValue: TaxonomicFilterGroupType.Events,
                hide: true,
            },
            {
                type: FilterType.Text,
                defaultValue: 'within',
            },
            {
                fieldKey: 'seq_time_value',
                type: FilterType.Number,
                defaultValue: '15',
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
        value: BehavioralEventType.HaveProperty,
        negation: false,
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
                fieldKey: 'value_property',
                type: FilterType.PersonPropertyValues,
            },
        ],
    },
    [BehavioralEventType.NotHaveProperty]: {
        type: BehavioralFilterKey.Person,
        value: BehavioralEventType.HaveProperty,
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
                fieldKey: 'value_property',
                type: FilterType.PersonPropertyValues,
            },
        ],
    },
    [BehavioralCohortType.InCohort]: {
        type: BehavioralFilterKey.Cohort,
        value: BehavioralCohortType.InCohort,
        negation: false,
        fields: [
            { fieldKey: 'key', type: FilterType.CohortId, defaultValue: 'id', hide: true },
            {
                fieldKey: 'value_property',
                type: FilterType.CohortValues,
            },
        ],
    },
    [BehavioralCohortType.NotInCohort]: {
        type: BehavioralFilterKey.Cohort,
        value: BehavioralCohortType.InCohort,
        negation: true,
        fields: [
            { fieldKey: 'key', type: FilterType.CohortId, defaultValue: 'id', hide: true },
            {
                fieldKey: 'value_property',
                type: FilterType.CohortValues,
            },
        ],
    },
    [BehavioralLifecycleType.PerformEventFirstTime]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.PerformEventFirstTime,
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '30',
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
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                type: FilterType.EventsAndActionsMathOperator,
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
            {
                type: FilterType.Text,
                defaultValue: 'periods',
            },
        ],
    },
    [BehavioralLifecycleType.StopPerformEvent]: {
        type: BehavioralFilterKey.Behavioral,
        value: BehavioralLifecycleType.StopPerformEvent,
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '15',
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
                defaultValue: '30',
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
        negation: false,
        fields: [
            {
                fieldKey: 'key',
                groupTypeFieldKey: 'event_type',
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
                defaultValue: '15',
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
                defaultValue: '30',
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
                    FieldOptionsType.PersonPropertyBehavioral,
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
    [FilterType.EventsAndActionsMathOperator]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.EventsAndActionsMathOperators]} />
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
                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                placeholder="Choose person property"
            />
        )
    },
    [FilterType.PersonPropertyValues]: function _renderField(p) {
        return p.criteria['operator'] &&
            [PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(p.criteria['operator']) ? (
            <></>
        ) : (
            <CohortPersonPropertiesValuesField
                {...(p as CohortPersonPropertiesValuesFieldProps)}
                propertyKey={p.criteria.key}
                operator={p.criteria['operator'] ?? undefined}
            />
        )
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

export const CRITERIA_VALIDATIONS: Record<
    string,
    (d: string | number | null | undefined) => CohortClientErrors | undefined
> = {
    [FilterType.EventsAndActions]: () => CohortClientErrors.EmptyEventsAndActions,
    [FilterType.EventProperties]: () => CohortClientErrors.EmptyEventProperties,
    [FilterType.PersonPropertyValues]: () => CohortClientErrors.EmptyPersonPropertyValues,
    [FilterType.EventType]: () => CohortClientErrors.EmptyEventType,
    [FilterType.Number]: (d) => (Number(d) > 1 ? undefined : CohortClientErrors.EmptyNumber),
    [FilterType.NumberTicker]: () => CohortClientErrors.EmptyNumberTicker,
    [FilterType.TimeUnit]: () => CohortClientErrors.EmptyTimeUnit,
    [FilterType.MathOperator]: () => CohortClientErrors.EmptyMathOperator,
    [FilterType.EventsAndActionsMathOperator]: () => CohortClientErrors.EmptyMathOperator,
    [FilterType.CohortId]: () => CohortClientErrors.EmptyCohortId,
    [FilterType.CohortValues]: () => CohortClientErrors.EmptyCohortValues,
    [FilterType.Value]: () => CohortClientErrors.EmptyValue,
    [FilterType.DateOperator]: () => CohortClientErrors.EmptyDateOperator,
    [FilterType.Actors]: () => CohortClientErrors.EmptyActors,
    [FilterType.Aggregation]: () => CohortClientErrors.EmptyAggregation,
    [FilterType.Behavioral]: () => CohortClientErrors.EmptyBehavioral,
}

export const COHORT_TYPE_OPTIONS: LemonSelectOptions<CohortTypeEnum> = [
    { value: CohortTypeEnum.Static, label: 'Static · Updated manually' },
    { value: CohortTypeEnum.Dynamic, label: 'Dynamic · Updates automatically' },
]

export const NEW_CRITERIA = {
    type: BehavioralFilterKey.Behavioral,
    value: BehavioralEventType.PerformEvent,
    event_type: TaxonomicFilterGroupType.Events,
    time_value: '30',
    time_interval: TimeUnitType.Day,
}

export const NEW_CRITERIA_GROUP: CohortCriteriaGroupFilter = {
    id: Math.random().toString().substr(2, 5),
    type: FilterLogicalOperator.Or,
    values: [NEW_CRITERIA],
}

export const NEW_COHORT: CohortType = {
    id: 'new',
    groups: [
        {
            id: Math.random().toString().substr(2, 5),
            matchType: PROPERTY_MATCH_TYPE,
            properties: [],
        },
    ],
    filters: {
        properties: {
            id: Math.random().toString().substr(2, 5),
            type: FilterLogicalOperator.Or,
            values: [NEW_CRITERIA_GROUP],
        },
    },
}

export const BEHAVIORAL_TYPE_TO_LABEL = {
    ...FIELD_VALUES[FieldOptionsType.EventBehavioral].values,
    ...FIELD_VALUES[FieldOptionsType.PersonPropertyBehavioral].values,
    ...FIELD_VALUES[FieldOptionsType.CohortBehavioral].values,
    ...FIELD_VALUES[FieldOptionsType.LifecycleBehavioral].values,
    ...SCALE_FIELD_VALUES[FieldOptionsType.EventBehavioral].values,
    ...SCALE_FIELD_VALUES[FieldOptionsType.LifecycleBehavioral].values,
}
