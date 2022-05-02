import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { BehavioralCohortType, BehavioralEventType, BehavioralLifecycleType } from '~/types'
import { CohortFieldLogicProps } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export enum FilterType {
    Behavioral = 'behavioral',
    Aggregation = 'aggregation',
    Actors = 'actors',
    TimeUnit = 'timeUnit',
    DateOperator = 'dateOperator',
    MathOperator = 'mathOperator',
    Value = 'value',
    Text = 'text',
    EventsAndActions = 'eventsAndActions',
    EventProperties = 'eventProperties',
    EventPropertyValues = 'eventPropertyValues',
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
    CohortBehavioral = 'cohortBehavioral',
    LifecycleBehavioral = 'lifecycleBehavioral',
    TimeUnits = 'timeUnits',
    DateOperators = 'dateOperators',
    MathOperators = 'mathOperators',
    ValueOptions = 'valueOptions',
}

export interface FieldValues {
    label: string
    values: LemonSelectOptions
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
    defaultValue?: string | number | null
    type: FilterType
    hide?: boolean // If field is hidden, key is included in final payload but no component is rendered
}

export interface FieldWithFieldKey extends Omit<Field, 'fieldKey'> {
    fieldKey: string
}

export interface Row {
    type: BehavioralFilterKey
    value: BehavioralFilterType
    fields: Field[]
    negation?: boolean
}

// CohortField

export interface CohortFieldBaseProps extends Omit<CohortFieldLogicProps, 'cohortFilterLogicKey'> {
    cohortFilterLogicKey?: string
}

export interface CohortSelectorFieldProps extends CohortFieldBaseProps {
    placeholder?: string
}

export interface CohortTaxonomicFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    placeholder?: string
    taxonomicGroupType?: TaxonomicFilterGroupType
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
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
