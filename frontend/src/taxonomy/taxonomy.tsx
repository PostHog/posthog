import * as coreFilterDefinitionsByGroup from './core-filter-definitions-by-group.json'
import { transformFilterDefinitions } from './transformations'

export const CORE_FILTER_DEFINITIONS_BY_GROUP = Object.entries(coreFilterDefinitionsByGroup).reduce(
    (acc, [key, group]) => ({
        ...acc,
        [key]: transformFilterDefinitions(group),
    }),
    {}
)
