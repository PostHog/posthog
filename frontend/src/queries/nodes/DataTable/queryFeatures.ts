import { Node } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isEventsQuery,
    isGroupsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
    isRevenueAnalyticsTopCustomersQuery,
    isRevenueExampleDataWarehouseTablesQuery,
    isRevenueExampleEventsQuery,
    isSessionAttributionExplorerQuery,
    isSessionsQuery,
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
    groupPropertyFilters,
    sessionPropertyFilters,
    linkDataButton,
    personsSearch,
    groupsSearch,
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

    if (
        isHogQLQuery(query) ||
        isEventsQuery(query) ||
        isSessionAttributionExplorerQuery(query) ||
        isRevenueExampleEventsQuery(query)
    ) {
        features.add(QueryFeature.dateRangePicker)
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.eventPropertyFilters)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.displayResponseError)
        features.add(QueryFeature.testAccountFilters)
    }

    if (isSessionsQuery(query)) {
        features.add(QueryFeature.dateRangePicker)
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.sessionPropertyFilters)
        features.add(QueryFeature.eventNameFilter)
        features.add(QueryFeature.eventPropertyFilters)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.displayResponseError)
        features.add(QueryFeature.testAccountFilters)
        features.add(QueryFeature.columnConfigurator)
        features.add(QueryFeature.selectAndOrderByColumns)
    }

    if (isRevenueExampleDataWarehouseTablesQuery(query)) {
        features.add(QueryFeature.columnsInResponse)
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

    if (isPersonsNode(query) || isActorsQuery(query)) {
        features.add(QueryFeature.personPropertyFilters)
        features.add(QueryFeature.personsSearch)

        if (isActorsQuery(query)) {
            features.add(QueryFeature.selectAndOrderByColumns)
            features.add(QueryFeature.columnsInResponse)
            features.add(QueryFeature.resultIsArrayOfArrays)
        }
    }

    if (isGroupsQuery(query)) {
        features.add(QueryFeature.groupPropertyFilters)
        features.add(QueryFeature.groupsSearch)
        features.add(QueryFeature.selectAndOrderByColumns)
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.columnConfigurator)
        features.add(QueryFeature.linkDataButton)
    }

    if (
        isWebOverviewQuery(query) ||
        isWebExternalClicksQuery(query) ||
        isWebStatsTableQuery(query) ||
        isWebGoalsQuery(query) ||
        isRevenueAnalyticsTopCustomersQuery(query)
    ) {
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.hideLoadNextButton)
        features.add(QueryFeature.displayResponseError)
    }

    if (isMarketingAnalyticsTableQuery(query)) {
        features.add(QueryFeature.columnsInResponse)
        features.add(QueryFeature.resultIsArrayOfArrays)
        features.add(QueryFeature.displayResponseError)
        features.add(QueryFeature.selectAndOrderByColumns)
    }

    if (isTracesQuery(query)) {
        features.add(QueryFeature.dateRangePicker)
        features.add(QueryFeature.eventPropertyFilters)
        features.add(QueryFeature.testAccountFilters)
        features.add(QueryFeature.columnConfigurator)
    }

    return features
}
