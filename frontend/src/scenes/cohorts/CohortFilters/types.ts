import { LemonSelectOptions } from 'lib/components/LemonSelect'

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
