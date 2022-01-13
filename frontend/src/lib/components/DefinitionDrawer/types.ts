import { EventOrPropType } from '~/types'

export enum TaxonomicType {
    Action = 'action',
    Event = 'event',
    EventProperty = 'event_property',
    PersonProperty = 'person_property',
    Element = 'element',
    Cohort = 'cohort',
    Group = 'group',
}

export type TaxonomicId = string | number

// Map that resolves definition types to type in api endpoint
export const drawerTypeToApiTypeMap: Record<TaxonomicType, string> = {
    [TaxonomicType.Action]: 'action', // TODO: Not implemented on server
    [TaxonomicType.Event]: 'event',
    [TaxonomicType.EventProperty]: 'property',
    [TaxonomicType.PersonProperty]: 'property',
    [TaxonomicType.Element]: 'element', // TODO: Not implemented
    [TaxonomicType.Cohort]: 'cohort', // TODO: Not implemented
    [TaxonomicType.Group]: 'group', // TODO: Not implemented
}

// Definition object sent to the API
export interface ApiDefinition extends Omit<Partial<EventOrPropType>, 'owner'> {
    owner?: string | number
}
