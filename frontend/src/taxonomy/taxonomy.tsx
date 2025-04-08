import { CoreFilterDefinition } from '~/types'

import * as coreFilterDefinitionsByGroup from './core-filter-definitions-by-group.json'
import { transformFilterDefinitions } from './transformations'

type CoreFilterDefinitionsGroup = keyof typeof coreFilterDefinitionsByGroup

export const CORE_FILTER_DEFINITIONS_BY_GROUP = Object.entries(coreFilterDefinitionsByGroup).reduce(
    (acc, [key, group]) => ({
        ...acc,
        [key]: transformFilterDefinitions(group),
    }),
    {} as Record<CoreFilterDefinitionsGroup, Record<string, CoreFilterDefinition>>
)

// We treat `$session_duration` as an event property in the context of series `math`, but it's fake in a sense
CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties.$session_duration =
    CORE_FILTER_DEFINITIONS_BY_GROUP.session_properties.$session_duration

CORE_FILTER_DEFINITIONS_BY_GROUP.numerical_event_properties = CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties

// Change "All Events" to empty string
CORE_FILTER_DEFINITIONS_BY_GROUP.events[''] = CORE_FILTER_DEFINITIONS_BY_GROUP.events['All Events']
delete CORE_FILTER_DEFINITIONS_BY_GROUP.events['All Events']

export const PROPERTY_KEYS = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties)
