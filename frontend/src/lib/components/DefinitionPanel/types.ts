import { EventDefinition, PropertyDefinition } from '~/types'

// All definition types are castable into event or event property definition. This may change when the scope of
// a definition changes.
export type DefinitionShapeType = EventDefinition & PropertyDefinition
