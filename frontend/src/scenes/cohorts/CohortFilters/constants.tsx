import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { CohortTypeEnum, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import {
    CohortEventFiltersField,
    CohortNumberField,
    CohortPersonPropertiesValuesField,
    CohortRelativeAndExactTimeField,
    CohortSelectorField,
    CohortTaxonomicField,
    CohortTextField,
} from 'scenes/cohorts/CohortFilters/CohortField'
import {
    BehavioralFilterKey,
    BehavioralFilterType,
    CohortClientErrors,
    CohortEventFiltersFieldProps,
    CohortFieldProps,
    CohortNumberFieldProps,
    CohortPersonPropertiesValuesFieldProps,
    CohortRelativeAndExactTimeFieldProps,
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
    SingleFieldDateType,
    TimeUnitType,
    ValueOptionType,
} from '~/types'

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
            [BaseMathType.TotalCount]: {
                label: 'Total count',
            },
            [BaseMathType.UniqueUsers]: {
                label: 'Unique users',
            },
            [BaseMathType.WeeklyActiveUsers]: {
                label: 'Weekly active users',
            },
            [BaseMathType.MonthlyActiveUsers]: {
                label: 'Monthly active users',
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
            [PropertyMathType.P75]: {
                label: '75th percentile',
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
        },
    },
    [FieldOptionsType.PersonPropertyBehavioral]: {
        label: 'Person Properties',
        type: FieldOptionsType.PersonPropertyBehavioral,
        values: {
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
        values: {},
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
    [FieldOptionsType.SingleFieldDateOperators]: {
        label: 'Date Operators',
        type: FieldOptionsType.SingleFieldDateOperators,
        values: {
            [SingleFieldDateType.IsDateExact]: {
                label: 'on the date',
            },
            [SingleFieldDateType.IsDateAfter]: {
                label: 'since',
            },
            [SingleFieldDateType.IsDateBefore]: {
                label: 'before',
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
                label: 'contains',
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
    [FieldOptionsType.EventsAndActionsMathOperators]: {
        label: 'Operators',
        type: FieldOptionsType.EventsAndActionsMathOperators,
        values: {
            [PropertyOperator.Exact]: {
                label: 'exactly',
            },
            [PropertyOperator.GreaterThanOrEqual]: {
                label: 'at least',
            },
            [PropertyOperator.LessThanOrEqual]: {
                label: 'at most',
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
                fieldKey: 'event_filters',
                type: FilterType.EventFilters,
            },
            {
                type: FilterType.Text,
                defaultValue: 'after',
            },
            {
                fieldKey: 'explicit_datetime',
                type: FilterType.RelativeAndExactTime,
                defaultValue: '-30d',
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
                fieldKey: 'event_filters',
                type: FilterType.EventFilters,
            },
            {
                type: FilterType.Text,
                defaultValue: 'after',
            },
            {
                fieldKey: 'explicit_datetime',
                type: FilterType.RelativeAndExactTime,
                defaultValue: '-30d',
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
                fieldKey: 'event_filters',
                type: FilterType.EventFilters,
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
                defaultValue: 'times after',
            },
            {
                fieldKey: 'explicit_datetime',
                type: FilterType.RelativeAndExactTime,
                defaultValue: '-30d',
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
                type: FilterType.PersonProperties,
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
                type: FilterType.PersonProperties,
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

export const COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME = Object.entries(ROWS)
    .filter(([_, row]) => row.fields.some((field) => field.type === FilterType.RelativeAndExactTime))
    .map(([eventType, _]) => eventType)

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
        return (
            <CohortSelectorField
                {...p}
                fieldOptionGroupTypes={[FieldOptionsType.MathOperators, FieldOptionsType.SingleFieldDateOperators]}
            />
        )
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
    [FilterType.PersonProperties]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                placeholder="Choose person property"
            />
        )
    },
    [FilterType.EventFilters]: function _renderField(p) {
        return <CohortEventFiltersField {...(p as CohortEventFiltersFieldProps)} />
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
    [FilterType.RelativeAndExactTime]: function _renderField(p) {
        return <CohortRelativeAndExactTimeField {...(p as CohortRelativeAndExactTimeFieldProps)} />
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
    [FilterType.EventFilters]: () => CohortClientErrors.EmptyEventFilters,
    [FilterType.PersonProperties]: () => CohortClientErrors.EmptyPersonProperties,
    [FilterType.PersonPropertyValues]: () => CohortClientErrors.EmptyPersonPropertyValues,
    [FilterType.EventType]: () => CohortClientErrors.EmptyEventType,
    [FilterType.Number]: (d) => (Number(d) > 1 ? undefined : CohortClientErrors.EmptyNumber),
    [FilterType.NumberTicker]: () => CohortClientErrors.EmptyNumberTicker,
    [FilterType.TimeUnit]: () => CohortClientErrors.EmptyTimeUnit,
    [FilterType.MathOperator]: () => CohortClientErrors.EmptyMathOperator,
    [FilterType.EventsAndActionsMathOperator]: () => CohortClientErrors.EmptyMathOperator,
    [FilterType.RelativeAndExactTime]: () => CohortClientErrors.EmptyRelativeAndExactTime,
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
    explicit_datetime: '-30d',
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

export const BEHAVIORAL_TYPE_TO_LABEL: Partial<Record<BehavioralFilterType, { label: string }>> = {
    ...FIELD_VALUES[FieldOptionsType.EventBehavioral].values,
    ...FIELD_VALUES[FieldOptionsType.PersonPropertyBehavioral].values,
    ...FIELD_VALUES[FieldOptionsType.CohortBehavioral].values,
    ...FIELD_VALUES[FieldOptionsType.LifecycleBehavioral].values,
    ...SCALE_FIELD_VALUES[FieldOptionsType.EventBehavioral].values,
    ...SCALE_FIELD_VALUES[FieldOptionsType.LifecycleBehavioral].values,
}
