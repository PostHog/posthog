import { personPropertiesModel } from '~/models/personPropertiesModel'
import { CohortType, PersonProperty } from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { LogicWrapper } from 'kea'

export type PropertyFilterGroup = {
    name: string
    type: string
    endpoint?: string
    logic?: LogicWrapper
    value?: string
    map?: (prop: any) => any
}

export const groups: PropertyFilterGroup[] = [
    {
        name: 'Event properties',
        type: 'event',
        endpoint: 'api/projects/@current/property_definitions',
    },
    {
        name: 'Person properties',
        type: 'person',
        logic: personPropertiesModel,
        value: 'personProperties',
        map: (property: PersonProperty): any => ({
            ...property,
            key: property.name,
        }),
    },
    {
        name: 'Cohorts',
        type: 'cohort',
        logic: cohortsModel,
        value: 'cohorts',
        map: (cohort: CohortType): any => ({
            ...cohort,
            key: cohort.id,
            name: cohort.name || '',
        }),
    },
]
