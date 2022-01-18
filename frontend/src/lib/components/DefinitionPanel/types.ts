import { EventDefinition, PropertyDefinition } from '~/types'

// Always must be a subset of TaxonomicFilterGroupType. Technically each enum here should be the singular version
// of its counterpart in TaxonomicFilterGroupType. i.e., 'events' really describes a single 'event' definition.
export enum DefinitionType {
    Actions = 'actions',
    Events = 'events',
    EventProperties = 'event_properties',
    PersonProperties = 'person_properties',
    Cohorts = 'cohorts',
    GroupsPrefix = 'groups',
}

export type DefinitionShapeType = EventDefinition & PropertyDefinition // All definition types are castable into event or event property definition.
