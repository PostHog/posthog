import { actions, afterMount, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isDefinitionStale } from 'lib/utils/definitions'

import { DateRange, ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { EventDefinitionType, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'

export const DEFAULT_ERROR_TRACKING_DATE_RANGE = { date_from: '-7d', date_to: null }

export const DEFAULT_ERROR_TRACKING_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
    }),
    reducers({
        dateRange: [
            DEFAULT_ERROR_TRACKING_DATE_RANGE as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        assignee: [
            null as ErrorTrackingIssueAssignee | null,
            {
                setAssignee: (_, { assignee }) => assignee,
            },
        ],
        filterGroup: [
            DEFAULT_ERROR_TRACKING_FILTER_GROUP as UniversalFiltersGroup,
            { persist: true },
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        filterTestAccounts: [
            false as boolean,
            { persist: true },
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    }),
    loaders({
        hasSentExceptionEvent: {
            __default: undefined as boolean | undefined,
            loadExceptionEventDefinition: async (): Promise<boolean> => {
                const exceptionDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$exception',
                })
                const definition = exceptionDefinition.results.find((r) => r.name === '$exception')
                return definition ? !isDefinitionStale(definition) : false
            },
        },
    }),

    afterMount(({ actions }) => {
        actions.loadExceptionEventDefinition()
    }),
])
