import { Node } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isEventsQuery,
    isHogQLQuery,
    isPersonsNode,
    isSessionAttributionExplorerQuery,
    isTracesQuery,
    isWebExternalClicksQuery,
    isWebGoalsQuery,
    isWebOverviewQuery,
    isWebStatsTableQuery,
} from '~/queries/utils'

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
    hideLoadNextButton,
    testAccountFilters,
    highlightExceptionEventRows,
}

export function getQueryFeatures(query: Node): Set<QueryFeature> {
    const features = new Set<QueryFeature>()

    if (isHogQLQuery(query) || isEventsQuery(query) || isSessionAttributionExplorerQuery(query)) {
        features.add(QueryFeature.dateRangePicker)
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.eventPropertyFilters)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.displayResponseError)
        features.add(QueryFeature.testAccountFilters)
    }

    if (isEventsQuery(query)) {
        features.add(QueryFeature.eventActionsColumn)
        features.add(QueryFeature.eventNameFilter)
        features.add(QueryFeature.savedEventsQueries)
        features.add(QueryFeature.columnConfigurator)
        features.add(QueryFeature.selectAndOrderByColumns)
    }

    if (isPersonsNode(query) || isActorsQuery(query)) {
        features.add(QueryFeature.personPropertyFilters)
        features.add(QueryFeature.personsSearch)

        if (isActorsQuery(query)) {
            features.add(QueryFeature.selectAndOrderByColumns)
            features.add(QueryFeature.columnsInResponse)
            features.add(QueryFeature.resultIsArrayOfArrays)
        }
    }

    if (
        isWebOverviewQuery(query) ||
        isWebExternalClicksQuery(query) ||
        isWebStatsTableQuery(query) ||
        isWebGoalsQuery(query)
    ) {
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.hideLoadNextButton)
    }

    if (isTracesQuery(query)) {
        features.add(QueryFeature.dateRangePicker)
        features.add(QueryFeature.eventPropertyFilters)
        features.add(QueryFeature.testAccountFilters)
    }

    return features
}
