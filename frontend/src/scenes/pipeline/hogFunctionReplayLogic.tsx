import equal from 'fast-deep-equal'
import { actions, connect, events, kea, key, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { EventsQuery, NodeKind } from '~/queries/schema'
import { escapePropertyAsHogQlIdentifier } from '~/queries/utils'
import { hogFunctionConfigurationLogic } from './hogfunctions/hogFunctionConfigurationLogic'

export const hogFunctionReplayLogic = kea([
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'hogFunctionReplayLogic', key]),
    connect({
        values: [hogFunctionConfigurationLogic, ['configuration', 'matchingFilters', 'groupTypes']],
      }),
    actions({
        changeDateRange: (after: string, before: string) => ({ after, before }),
    }),
    reducers({
        dateRange: [
            { after: '-7d', before: undefined },
            {
                changeDateRange: (_, { after, before }: { after: string, before: string }) => ({ after, before }),
            },
        ],
    }),
    selectors(({  }) => ({
        baseEventsQuery: [
            (s) => [s.configuration, s.matchingFilters, s.groupTypes, s.dateRange],
            (configuration, matchingFilters, groupTypes, dateRange): EventsQuery | null => {
                const query: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    filterTestAccounts: configuration.filters?.filter_test_accounts,
                    fixedProperties: [matchingFilters],
                    select: ['*', 'person'],
                    after: dateRange.after,
                    before: dateRange.before,
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
    })),
    loaders(({ values }) => ({
        events: [
            null as string[] | null,
            {
                loadEvents: async () => {
                    const response = await api.query(values.baseEventsQuery)
                    response.results = response.results.map((x: any) => ({ ...x[0], retries: [] }))
                    return response
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        changeDateRange: () => {
            actions.loadEvents({ refresh: 'blocking' })
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadEvents({ refresh: 'blocking' })
        },
    })),
])
