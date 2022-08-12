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
            { key: BaseMathType.Total, label: 'Total' },
            { key: BaseMathType.DailyActive, label: 'Unique' },
            { key: BaseMathType.WeeklyActive, label: 'Count of weekly active' },
            { key: BaseMathType.MonthlyActive, label: 'Count of weekly active' },
        ],
    },
    [FieldOptionsType.PropertyAggregation]: {
        label: 'Property Aggregation',
        type: FieldOptionsType.PropertyAggregation,
        values: [
            { key: PropertyMathType.Average, label: 'Average' },
            { key: PropertyMathType.Sum, label: 'Sum' },
            { key: PropertyMathType.Minimum, label: 'Minimum' },
            { key: PropertyMathType.Maximum, label: 'Maximum' },
            { key: PropertyMathType.Median, label: 'Median' },
            { key: PropertyMathType.P90, label: '90th percentile' },
            { key: PropertyMathType.P95, label: '95th percentile' },
            { key: PropertyMathType.P99, label: '99th percentile' },
        ],
    },
    [FieldOptionsType.Actors]: {
        label: 'Actors',
        type: FieldOptionsType.Actors,
        values: [{ key: ActorGroupType.Person, label: 'Persons' }],
    },
    [FieldOptionsType.EventBehavioral]: {
        label: 'Behavioral',
        type: FieldOptionsType.EventBehavioral,
        values: [
            {
                key: BehavioralEventType.PerformEvent,
                label: 'Completed event',
            },
            {
                key: BehavioralEventType.NotPerformedEvent,
                label: 'Did not complete event',
            },
            {
                key: BehavioralEventType.PerformMultipleEvents,
                label: 'Completed an event multiple times',
            },
        ],
    },
    [FieldOptionsType.PersonPropertyBehavioral]: {
        label: 'Person Properties',
        type: FieldOptionsType.PersonPropertyBehavioral,
        values: [
            { key: BehavioralEventType.HaveProperty, label: 'Have the property' },
            { key: BehavioralEventType.NotHaveProperty, label: 'Do not have the property' },
        ],
    },
    [FieldOptionsType.CohortBehavioral]: {
        label: 'Cohorts',
        type: FieldOptionsType.CohortBehavioral,
        values: [
            { key: BehavioralCohortType.InCohort, label: 'In cohort' },
            { key: BehavioralCohortType.NotInCohort, label: 'Not in cohort' },
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
            { key: TimeUnitType.Day, label: 'days' },
            { key: TimeUnitType.Week, label: 'weeks' },
            { key: TimeUnitType.Month, label: 'months' },
            { key: TimeUnitType.Year, label: 'years' },
        ],
    },
    [FieldOptionsType.DateOperators]: {
        label: 'Date Operators',
        type: FieldOptionsType.DateOperators,
        values: [
            { key: DateOperatorType.BeforeTheLast, label: 'before the last' },
            { key: DateOperatorType.Between, label: 'between' },
            { key: DateOperatorType.NotBetween, label: 'not between' },
            { key: DateOperatorType.OnTheDate, label: 'on the date' },
            { key: DateOperatorType.NotOnTheDate, label: 'not on the date' },
            { key: DateOperatorType.Since, label: 'since' },
            { key: DateOperatorType.Before, label: 'before' },
            { key: DateOperatorType.IsSet, label: 'is set' },
        ],
    },
    [FieldOptionsType.MathOperators]: {
        label: 'Operators',
        type: FieldOptionsType.MathOperators,
        values: [
            { key: PropertyOperator.Exact, label: 'equals' },
            { key: PropertyOperator.IsNot, label: 'does not equal' },
            { key: PropertyOperator.IContains, label: 'contain' },
            { key: PropertyOperator.NotIContains, label: 'does not contain' },
            { key: PropertyOperator.Regex, label: 'matches regex' },
            { key: PropertyOperator.NotRegex, label: 'does not match regex' },
            { key: PropertyOperator.GreaterThan, label: 'greater than' },
            { key: PropertyOperator.GreaterThanOrEqual, label: 'greater than or equal to' },
            { key: PropertyOperator.LessThan, label: 'less than' },
            { key: PropertyOperator.LessThanOrEqual, label: 'less than or equal to' },
            { key: PropertyOperator.IsSet, label: 'is set' },
            { key: PropertyOperator.IsNotSet, label: 'is not set' },
            { key: PropertyOperator.Between, label: 'between' },
            { key: PropertyOperator.NotBetween, label: 'not between' },
            { key: PropertyOperator.Minimum, label: 'minimum' },
            { key: PropertyOperator.Maximum, label: 'maximum' },
        ],
    },
    [FieldOptionsType.EventsAndActionsMathOperators]: {
        label: 'Operators',
        type: FieldOptionsType.EventsAndActionsMathOperators,
        values: [
            { key: PropertyOperator.Exact, label: 'exactly' },
            { key: PropertyOperator.GreaterThanOrEqual, label: 'at least' },
            { key: PropertyOperator.LessThanOrEqual, label: 'at most' },
        ],
    },
    [FieldOptionsType.ValueOptions]: {
        label: 'Value Options',
        type: FieldOptionsType.ValueOptions,
        values: [
            { key: ValueOptionType.MostRecent, label: 'most recent value' },
            { key: ValueOptionType.Previous, label: 'previous value' },
            { key: ValueOptionType.OnDate, label: 'value on the date' },
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
    { key: CohortTypeEnum.Static, label: 'Static · Updated manually' },
    { key: CohortTypeEnum.Dynamic, label: 'Dynamic · Updates automatically' },
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
