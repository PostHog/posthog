import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { CohortFieldLogicProps } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'

import {
    AnyCohortCriteriaType,
    BehavioralCohortType,
    BehavioralEventType,
    BehavioralLifecycleType,
    PropertyFilterValue,
    PropertyOperator,
} from '~/types'

export enum FilterType {
    Behavioral = 'behavioral',
    Aggregation = 'aggregation',
    Actors = 'actors',
    TimeUnit = 'timeUnit',
    DateOperator = 'dateOperator',
    MathOperator = 'mathOperator',
    EventsAndActionsMathOperator = 'eventsAndActionsMathOperator',
    Value = 'value',
    Text = 'text',
    EventsAndActions = 'eventsAndActions',
    RelativeAndExactTime = 'relativeAndExactTime',
    EventFilters = 'eventFilters',
    PersonProperties = 'personProperties',
    PersonPropertyValues = 'personPropertyValues',
    EventType = 'eventType',
    Number = 'number',
    NumberTicker = 'numberTicker',
    CohortValues = 'cohortValues',
    CohortId = 'cohortId',
}

export enum FieldOptionsType {
    EventAggregation = 'eventAggregation',
    PropertyAggregation = 'propertyAggregation',
    Actors = 'actors',
    EventBehavioral = 'eventBehavioral',
    PersonPropertyBehavioral = 'personPropertyBehavioral',
    CohortBehavioral = 'cohortBehavioral',
    LifecycleBehavioral = 'lifecycleBehavioral',
    TimeUnits = 'timeUnits',
    DateOperators = 'dateOperators',
    SingleFieldDateOperators = 'singleFieldDateOperators',
    MathOperators = 'mathOperators',
    ValueOptions = 'valueOptions',
    EventsAndActionsMathOperators = 'eventsAndActionsMathOperators',
}

export interface CohortSelectOption {
    label: string
}

export interface FieldValues {
    label: string
    values: Record<string | number, CohortSelectOption>
    type: FieldOptionsType
}

export type BehavioralFilterType = BehavioralEventType | BehavioralCohortType | BehavioralLifecycleType

export enum BehavioralFilterKey {
    Behavioral = 'behavioral',
    Cohort = 'cohort',
    Person = 'person',
}

export interface Field {
    fieldKey?: string
    groupTypeFieldKey?: string
    defaultValue?: string | number | null
    type: FilterType
    hide?: boolean // If field is hidden, key is included in final payload but no component is rendered
}

export interface FieldWithFieldKey extends Omit<Field, 'fieldKey'> {
    fieldKey: string
}

export interface Row {
    type: BehavioralFilterKey
    value?: BehavioralFilterType // Optional since some payloads override the value field
    fields: Field[]
    negation: boolean
}

// CohortField

export interface CohortFieldBaseProps extends Omit<CohortFieldLogicProps, 'cohortFilterLogicKey'> {
    cohortFilterLogicKey?: string
    groupIndex?: number
    index?: number
}

export interface CohortSelectorFieldProps extends CohortFieldBaseProps {
    placeholder?: string
}

export interface CohortTaxonomicFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    groupTypeFieldKey?: keyof AnyCohortCriteriaType
    placeholder?: string
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    fieldOptionGroupTypes: never
}

export interface CohortPersonPropertiesValuesFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    fieldOptionGroupTypes: never
    propertyKey: PropertyFilterValue | undefined
    operator?: PropertyOperator
}

export interface CohortEventFiltersFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    fieldOptionGroupTypes: never
}

export interface CohortRelativeAndExactTimeFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    fieldOptionGroupTypes: never
}

export interface CohortTextFieldProps extends CohortFieldBaseProps {
    value: string
}

export interface CohortNumberFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    fieldOptionGroupTypes: never
}

export type CohortFieldProps =
    | CohortSelectorFieldProps
    | CohortNumberFieldProps
    | CohortTaxonomicFieldProps
    | CohortTextFieldProps
    | CohortPersonPropertiesValuesFieldProps
    | CohortEventFiltersFieldProps
    | CohortRelativeAndExactTimeFieldProps

export enum CohortClientErrors {
    NegationCriteriaMissingOther = 'Negation criteria can only be used when matching all criteria (AND), and must be accompanied by at least one positive matching criteria.',
    NegationCriteriaCancel = 'These criteria cancel each other out, and would result in no matching persons.',
    PeriodTimeMismatch = 'The lower bound period value must not be greater than the upper bound value.',
    SequentialTimeMismatch = 'The lower bound period sequential time value must not be greater than the upper bound time value.',
    EmptyEventsAndActions = 'Event or action cannot be empty.',
    EmptyEventFilters = 'Event filters cannot be empty.',
    EmptyPersonProperties = 'Person property name cannot be empty.',
    EmptyPersonPropertyValues = 'Person property value cannot be empty',
    EmptyEventType = 'Event type cannot be empty.',
    EmptyNumber = 'Period values must be at least 1 day and cannot be empty.',
    EmptyNumberTicker = 'Number cannot be empty.',
    EmptyTimeUnit = 'Time interval cannot be empty.',
    EmptyRelativeAndExactTime = 'Time value cannot be empty.',
    EmptyMathOperator = 'Math operator cannot be empty.',
    EmptyCohortId = 'Cohort id cannot be empty.',
    EmptyCohortValues = 'Cohort value cannot be empty.',
    EmptyValue = 'Event property value selector cannot be empty.',
    EmptyDateOperator = 'Date cannot be empty or invalid.',
    EmptyActors = 'Actors selector cannot be empty.',
    EmptyAggregation = 'Aggregation selector cannot be empty.',
    EmptyBehavioral = 'Behavioral selector cannot be empty.',
}
