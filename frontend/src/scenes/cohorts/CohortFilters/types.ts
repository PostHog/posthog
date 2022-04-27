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
    key?: string
    value?: string | number | null
    type: FilterType
    hide?: boolean // If field is hidden, key is included in final payload but no component is rendered
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
    groupedValues?: Record<string, any>[] // entire row's values. contains information about other fields in row
}

export interface CohortSelectorFieldProps extends CohortFieldBaseProps {
    placeholder?: string
}

export interface CohortTaxonomicFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    placeholder?: string
    taxonomicGroupType?: TaxonomicFilterGroupType
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    fieldOptionGroupTypes: never
    onTaxonomicGroupChange?: (group: TaxonomicFilterGroupType) => void
}

export interface CohortTextFieldProps {
    value: string
    groupedValues?: Record<string, any>[]
}

export interface CohortNumberFieldProps extends Omit<CohortFieldBaseProps, 'fieldOptionGroupTypes'> {
    fieldOptionGroupTypes: never
}

export type CohortFieldProps = CohortSelectorFieldProps | CohortNumberFieldProps | CohortTaxonomicFieldProps
