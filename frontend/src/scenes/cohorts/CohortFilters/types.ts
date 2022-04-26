import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { BehavioralCohortType, BehavioralEventType, BehavioralLifecycleType } from '~/types'

export enum FilterTypes {
    Behavioral = 'behavioral',
    Aggregation = 'aggregation',
    Actors = 'actors',
    TimeUnit = 'timeUnit',
    DateOperator = 'dateOperator',
    MathOperator = 'mathOperator',
    Value = 'value',
    Text = 'text',
    Events = 'events',
    EventProperties = 'eventProperties',
    EventPropertyValues = 'eventPropertyValues',
    Number = 'number',
    NumberTicker = 'numberTicker',
}

export enum FilterGroupTypes {
    EventAggregation = 'eventAggregation',
    PropertyAggregation = 'propertyAggregation',
    Actors = 'actors',
    EventBehavioral = 'eventBehavioral',
    CohortBehavioral = 'cohortBehavioral',
    LifecycleBehavioral = 'lifecycleBehavioral',
    TimeUnits = 'timeUnits',
    DateOperators = 'dateOperators',
    Operators = 'operators',
    ValueOptions = 'valueOptions',
}

export interface GroupOption {
    label: string
    values: LemonSelectOptions
    type: FilterGroupTypes
}

export type BehavioralFilterType = BehavioralEventType | BehavioralCohortType | BehavioralLifecycleType

export interface Atom {
    key?: string
    value?: string | null
    type?: FilterTypes
}

export interface AtomGroup {
    type?: BehavioralFilterType
    atoms: Atom[]
}
