import {
    isEventsQuery,
    isHogQLQuery,
    isPersonsNode,
    isPersonsQuery,
    isWebOverviewQuery,
    isWebStatsTableQuery,
    isWebTopClicksQuery,
} from '~/queries/utils'
import { Node } from '~/queries/schema'

export enum QueryFeature {
    columnsInResponse,
    eventActionsColumn,
    dateRangePicker,
    eventNameFilter,
    eventPropertyFilters,
    personPropertyFilters,
    personsSearch,
    savedEventsQueries,
    columnConfigurator,
    resultIsArrayOfArrays,
    selectAndOrderByColumns,
    displayResponseError,
}

export function getQueryFeatures(query: Node): Set<QueryFeature> {
    const features = new Set<QueryFeature>()

    if (isHogQLQuery(query) || isEventsQuery(query)) {
        features.add(QueryFeature.dateRangePicker)
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.eventPropertyFilters)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.displayResponseError)
    }

    if (isEventsQuery(query)) {
        features.add(QueryFeature.eventActionsColumn)
        features.add(QueryFeature.eventNameFilter)
        features.add(QueryFeature.savedEventsQueries)
        features.add(QueryFeature.columnConfigurator)
        features.add(QueryFeature.selectAndOrderByColumns)
    }

    if (isPersonsNode(query) || isPersonsQuery(query)) {
        features.add(QueryFeature.personPropertyFilters)
        features.add(QueryFeature.personsSearch)

        if (isPersonsQuery(query)) {
            features.add(QueryFeature.selectAndOrderByColumns)
            features.add(QueryFeature.columnsInResponse)
            features.add(QueryFeature.resultIsArrayOfArrays)
        }
    }

    if (isWebOverviewQuery(query) || isWebTopClicksQuery(query) || isWebStatsTableQuery(query)) {
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.resultIsArrayOfArrays)
    }

    return features
}
