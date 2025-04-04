import * as coreFilterDefinitionsByGroup from './core-filter-definitions-by-group.json'
import { transformFilterDefinitions } from './transformations'

export const CORE_FILTER_DEFINITIONS_BY_GROUP = Object.entries(coreFilterDefinitionsByGroup).reduce(
    (acc, [key, group]) => ({
        ...acc,
        [key]: transformFilterDefinitions(group),
    }),
    {}
)

// We treat `$session_duration` as an event property in the context of series `math`, but it's fake in a sense
CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties.$session_duration =
    CORE_FILTER_DEFINITIONS_BY_GROUP.session_properties.$session_duration

CORE_FILTER_DEFINITIONS_BY_GROUP.numerical_event_properties = CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties
