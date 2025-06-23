import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'

import { groupsModel } from '~/models/groupsModel'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { EventsNode, EventsQuery, EventsQueryResponse, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier, setLatestVersionsOnQuery } from '~/queries/utils'
import {
    BaseMathType,
    ChartDisplayType,
    CyclotronJobInvocationGlobals,
    CyclotronJobTestInvocationResult,
} from '~/types'

import { hogFunctionConfigurationLogic, sanitizeConfiguration } from '../configuration/hogFunctionConfigurationLogic'
import type { hogFunctionTestingLogicType } from './hogFunctionTestingLogicType'

export interface HogFunctionTestingLogicProps {
    id: string
}

export interface EventsResultType {
    before: string | undefined
    results: EventsQueryResponse['results']
}

export interface CyclotronJobTestInvocationResultWithEventId extends CyclotronJobTestInvocationResult {
    eventId: string
}

const PAGE_ROWS = 20

export const hogFunctionTestingLogic = kea<hogFunctionTestingLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogFunctionTestingLogic', key]),
    props({} as HogFunctionTestingLogicProps),
    key(({ id }: HogFunctionTestingLogicProps) => id),
    connect(() => ({
        values: [
            hogFunctionConfigurationLogic,
            ['configuration', 'matchingFilters', 'templateId'],
            groupsModel,
            ['groupTypes'],
        ],
    })),
    actions({
        changeDateRange: (after: string | null, before: string | null) => ({ after, before }),
        addLoadingRetry: (eventId: string) => ({ eventId }),
        removeLoadingRetry: (eventId: string) => ({ eventId }),
        increaseCurrentPage: (timestamp: string | undefined) => ({ timestamp }),
        decreaseCurrentPage: true,
        resetCurrentPage: true,
        expandRow: (eventId: string) => ({ eventId }),
        collapseRow: (eventId: string) => ({ eventId }),
        resetCollapsedRows: true,
        selectForRetry: (eventIds: string[]) => ({ eventIds }),
        deselectForRetry: (eventIds: string[]) => ({ eventIds }),
        resetSelectedForRetry: true,
        setSelectingMany: (selectingMany: boolean) => ({ selectingMany }),
    }),
    reducers({
        dateRange: [
            { after: '-7d', before: null } as { after: string | null; before: string | null },
            {
                changeDateRange: (_, { after, before }: { after: string | null; before: string | null }) => ({
                    after,
                    before,
                }),
            },
        ],
        loadingRetries: [
            [] as string[],
            {
                addLoadingRetry: (state, { eventId }: { eventId: string }) => [...state, eventId],
                removeLoadingRetry: (state, { eventId }: { eventId: string }) =>
                    state.filter((id: string) => id !== eventId),
            },
        ],
        pageTimestamps: [
            [] as (string | undefined)[],
            {
                increaseCurrentPage: (state, { timestamp }: { timestamp: string | undefined }) => [...state, timestamp],
                decreaseCurrentPage: (state) => [...state.filter((_, i) => i !== state.length - 1)],
                resetCurrentPage: () => [],
            },
        ],
        expandedRows: [
            [] as string[],
            {
                expandRow: (state, { eventId }: { eventId: string }) => [...state, eventId],
                collapseRow: (state, { eventId }: { eventId: string }) => [
                    ...state.filter((id: string) => id !== eventId),
                ],
                resetCollapsedRows: () => [],
            },
        ],
        selectingMany: [
            false as boolean,
            {
                setSelectingMany: (_, { selectingMany }: { selectingMany: boolean }) => selectingMany,
            },
        ],
        selectedForRetry: [
            [] as string[],
            {
                selectForRetry: (state, { eventIds }: { eventIds: string[] }) => [...new Set([...state, ...eventIds])],
                deselectForRetry: (state, { eventIds }: { eventIds: string[] }) => [
                    ...state.filter((id: string) => !eventIds.includes(id)),
                ],
                resetSelectedForRetry: () => [],
            },
        ],
    }),
    loaders(({ values, props, actions }) => ({
        events: [
            { results: [], before: undefined } as EventsResultType,
            {
                loadEvents: async () => {
                    if (!values.baseEventsQuery) {
                        return { results: [], before: undefined }
                    }
                    const response = await api.query(values.baseEventsQuery)
                    return {
                        ...response,
                        before: values.dateRange.before ?? undefined,
                    }
                },
                loadNextEventsPage: async () => {
                    if (!values.nextQuery) {
                        return { ...values.events, before: undefined }
                    }
                    actions.increaseCurrentPage(values.events.before)
                    const response = await api.query(values.nextQuery)
                    return {
                        ...response,
                        before: values.nextQuery.before,
                    }
                },
                loadPreviousEventsPage: async () => {
                    if (!values.previousQuery) {
                        return { ...values.events, before: undefined }
                    }
                    const response = await api.query(values.previousQuery)
                    actions.decreaseCurrentPage()
                    return {
                        ...response,
                        before: values.previousQuery.before,
                    }
                },
            },
        ],
        totalEvents: [
            0 as number,
            {
                loadTotalEvents: async () => {
                    if (!values.totalEventsQuery) {
                        return 0
                    }
                    const response = await api.query(values.totalEventsQuery)
                    return response.results[0]?.aggregated_value ?? 0
                },
            },
        ],
        retries: [
            [] as CyclotronJobTestInvocationResultWithEventId[],
            {
                retryInvocation: async ({
                    eventId,
                    globals,
                }: {
                    eventId: string
                    globals: CyclotronJobInvocationGlobals
                }) => {
                    actions.addLoadingRetry(eventId)
                    const configuration = sanitizeConfiguration(values.configuration) as Record<string, any>
                    configuration.template_id = values.templateId

                    let res: CyclotronJobTestInvocationResult
                    try {
                        res = await api.hogFunctions.createTestInvocation(props.id ?? 'new', {
                            globals,
                            mock_async_functions: false,
                            configuration,
                        })

                        actions.removeLoadingRetry(eventId)
                        const retry: CyclotronJobTestInvocationResultWithEventId = {
                            eventId: eventId,
                            ...res,
                        }

                        return [...values.retries, retry]
                    } catch (e) {
                        lemonToast.error(`An unexpected server error occurred while testing the function. ${e}`)
                    }

                    actions.removeLoadingRetry(eventId)
                    return [...values.retries]
                },
            },
        ],
    })),
    selectors(({ values }) => ({
        baseEventsQuery: [
            (s) => [s.configuration, s.matchingFilters, s.groupTypes, s.dateRange],
            (configuration, matchingFilters, groupTypes, dateRange): EventsQuery | null => {
                const query: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    filterTestAccounts: configuration.filters?.filter_test_accounts,
                    fixedProperties: [matchingFilters],
                    limit: PAGE_ROWS,
                    select: ['*', 'person', 'timestamp'],
                    after: dateRange?.after ?? undefined,
                    before: dateRange?.before ?? undefined,
                    orderBy: ['timestamp DESC'],
                    modifiers: {
                        personsOnEventsMode: 'person_id_no_override_properties_on_events',
                    },
                }
                groupTypes.forEach((groupType) => {
                    const name = escapePropertyAsHogQLIdentifier(groupType.group_type)
                    query.select.push(
                        `tuple(${name}.created_at, ${name}.index, ${name}.key, ${name}.properties, ${name}.updated_at)`
                    )
                })
                return setLatestVersionsOnQuery(query)
            },
            { resultEqualityCheck: equal },
        ],
        totalEventsQuery: [
            (s) => [s.configuration, s.matchingFilters, s.dateRange],
            (configuration, matchingFilters, dateRange): TrendsQuery | null => {
                return setLatestVersionsOnQuery({
                    kind: NodeKind.TrendsQuery,
                    filterTestAccounts: configuration.filters?.filter_test_accounts,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: null,
                            name: 'All Events',
                            math: BaseMathType.TotalCount,
                        } satisfies EventsNode,
                    ],
                    properties: matchingFilters,
                    dateRange: {
                        date_from: dateRange.after,
                        date_to: dateRange.before,
                    },
                    trendsFilter: {
                        display: ChartDisplayType.BoldNumber,
                    },
                    modifiers: {
                        personsOnEventsMode: 'person_id_no_override_properties_on_events',
                    },
                })
            },
            { resultEqualityCheck: equal },
        ],
        eventsWithRetries: [
            (s) => [s.events, s.retries],
            (events: { results: any[] }, retries: CyclotronJobTestInvocationResultWithEventId[]) =>
                events.results.map((row) => [
                    ...row.slice(0, 3),
                    retries.filter((r) => r.eventId === row[0].uuid),
                    ...row.slice(3),
                ]),
        ],
        nextQuery: [
            (s) => [s.baseEventsQuery, s.events],
            (baseEventsQuery, events): EventsQuery | null => {
                if (!baseEventsQuery || !events) {
                    return null
                }
                const typedResults = events?.results
                const sortColumnIndex = baseEventsQuery?.select
                    .map((hql: any) => removeExpressionComment(hql))
                    .indexOf('timestamp')
                if (sortColumnIndex !== -1) {
                    const lastTimestamp = typedResults?.[typedResults.length - 1]?.[sortColumnIndex]
                    if (lastTimestamp) {
                        const newQuery: EventsQuery = {
                            ...baseEventsQuery,
                            before: lastTimestamp,
                            limit: PAGE_ROWS,
                        }
                        return newQuery
                    }
                }
                return null
            },
        ],
        previousQuery: [
            (s) => [s.baseEventsQuery, s.events],
            (baseEventsQuery, events): EventsQuery | null => {
                if (!baseEventsQuery || !events) {
                    return null
                }
                const lastTimestamp = values.pageTimestamps[values.pageTimestamps.length - 1]
                const newQuery: EventsQuery = {
                    ...baseEventsQuery,
                    before: lastTimestamp,
                    limit: PAGE_ROWS,
                }
                return newQuery
            },
        ],
    })),
    listeners(({ actions }) => ({
        changeDateRange: () => {
            actions.loadEvents()
        },
        loadEvents: () => {
            actions.loadTotalEvents()
            actions.resetCurrentPage()
            actions.resetCollapsedRows()
            actions.resetSelectedForRetry()
        },
        increaseCurrentPage: () => {
            actions.resetSelectedForRetry()
        },
        decreaseCurrentPage: () => {
            actions.resetSelectedForRetry()
        },
    })),
    subscriptions(({ actions, values }) => ({
        configuration: () => {
            if (values.configuration?.name) {
                actions.loadEvents()
                actions.loadTotalEvents()
            }
        },
    })),
    beforeUnload(({ values, cache }) => ({
        enabled: () => !cache.disabledBeforeUnload && values.loadingRetries.length > 0,
        message: 'You have running tests that will be discarded if you leave. Are you sure?',
        onConfirm: () => {
            cache.disabledBeforeUnload = true
        },
    })),
])
