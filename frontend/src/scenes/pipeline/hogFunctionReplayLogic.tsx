import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { groupsModel } from '~/models/groupsModel'
import { EventsNode, EventsQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQlIdentifier } from '~/queries/utils'

import type { hogFunctionReplayLogicType } from './hogFunctionReplayLogicType'
import {
    convertToHogFunctionInvocationGlobals,
    hogFunctionConfigurationLogic,
    sanitizeConfiguration,
} from './hogfunctions/hogFunctionConfigurationLogic'
import { BaseMathType, ChartDisplayType } from '~/types'

export interface HogFunctionReplayLogicProps {
    id: string
}

export const hogFunctionReplayLogic = kea<hogFunctionReplayLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogFunctionReplayLogic', key]),
    props({} as HogFunctionReplayLogicProps),
    key(({ id }: HogFunctionReplayLogicProps) => id),
    connect({
        values: [
            hogFunctionConfigurationLogic,
            ['configuration', 'matchingFilters', 'templateId'],
            groupsModel,
            ['groupTypes'],
        ],
    }),
    actions({
        changeDateRange: (after: string | null, before: string | null) => ({ after, before }),
        addLoadingRetry: (eventId: string) => ({ eventId }),
        removeLoadingRetry: (eventId: string) => ({ eventId }),
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
    }),
    loaders(({ values, props, actions }) => ({
        events: [
            [] as any[],
            {
                loadEvents: async () => {
                    if (!values.baseEventsQuery) {
                        return []
                    }
                    console.log({ query: values.baseEventsQuery })
                    const response = await api.query(values.baseEventsQuery)
                    return response.results
                },
                loadNextEvents: async () => {
                    if (!values.baseEventsQuery) {
                        return []
                    }
                    const response = await api.query(values.baseEventsQuery)
                    return [...response.results]
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
                    console.log({ response, count: response.results[0] })
                    return response.results[0]?.aggregated_value ?? 0
                },
            },
        ],
        retries: [
            [] as any[],
            {
                retryHogFunction: async (row: any) => {
                    actions.addLoadingRetry(row[0].uuid)
                    const globals = convertToHogFunctionInvocationGlobals(row[0], row[1])
                    globals.groups = {}
                    values.groupTypes.forEach((groupType, index) => {
                        const tuple = row?.[3 + index]
                        if (tuple && Array.isArray(tuple) && tuple[2]) {
                            let properties = {}
                            try {
                                properties = JSON.parse(tuple[3])
                            } catch (e) {
                                // Ignore
                            }
                            globals.groups![groupType.group_type] = {
                                type: groupType.group_type,
                                index: tuple[1],
                                id: tuple[2], // TODO: rename to "key"?
                                url: `${window.location.origin}/groups/${tuple[1]}/${encodeURIComponent(tuple[2])}`,
                                properties,
                            }
                        }
                    })
                    globals.source = {
                        name: values.configuration?.name ?? 'Unnamed',
                        url: window.location.href.split('#')[0],
                    }

                    const configuration = sanitizeConfiguration(values.configuration) as Record<string, any>
                    configuration.template_id = values.templateId

                    let res: any
                    try {
                        res = await api.hogFunctions.createTestInvocation(props.id ?? 'new', {
                            globals,
                            mock_async_functions: false,
                            configuration,
                        })
                    } catch (e) {
                        lemonToast.error(`An unexpected server error occurred while testing the function. ${e}`)
                    }

                    actions.removeLoadingRetry(row[0].uuid)
                    return [
                        {
                            eventId: row[0].uuid,
                            ...res,
                        },
                        ...values.retries,
                    ]
                },
            },
        ],
    })),
    selectors(() => ({
        baseEventsQuery: [
            (s) => [s.configuration, s.matchingFilters, s.groupTypes, s.dateRange],
            (configuration, matchingFilters, groupTypes, dateRange): EventsQuery | null => {
                const query: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    filterTestAccounts: configuration.filters?.filter_test_accounts,
                    fixedProperties: [matchingFilters],
                    limit: 20,
                    select: ['*', 'person'],
                    after: dateRange?.after ?? undefined,
                    before: dateRange?.before ?? undefined,
                    orderBy: ['timestamp DESC'],
                }
                groupTypes.forEach((groupType) => {
                    const name = escapePropertyAsHogQlIdentifier(groupType.group_type)
                    query.select.push(
                        `tuple(${name}.created_at, ${name}.index, ${name}.key, ${name}.properties, ${name}.updated_at)`
                    )
                })
                return query
            },
            { resultEqualityCheck: equal },
        ],
        totalEventsQuery: [
            (s) => [s.configuration, s.matchingFilters, s.dateRange],
            (configuration, matchingFilters, dateRange): TrendsQuery | null => {
                return {
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
                }
            },
            { resultEqualityCheck: equal },
        ],
        eventsWithRetries: [
            (s) => [s.events, s.retries],
            (events: any[], retries: any[]) =>
                events.map((row) => [
                    ...row.slice(0, 2),
                    retries.filter((r) => r.eventId === row[0].uuid),
                    ...row.slice(2),
                ]),
        ],
    })),
    listeners(({ actions }) => ({
        changeDateRange: () => {
            actions.loadEvents()
            actions.loadTotalEvents()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadEvents()
            actions.loadTotalEvents()
        },
    })),
])
