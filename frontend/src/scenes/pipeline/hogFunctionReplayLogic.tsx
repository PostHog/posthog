import equal from 'fast-deep-equal'
import { actions, connect, events, kea, key, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { EventsQuery, NodeKind } from '~/queries/schema'
import { escapePropertyAsHogQlIdentifier } from '~/queries/utils'
import {
    convertToHogFunctionInvocationGlobals,
    hogFunctionConfigurationLogic,
    sanitizeConfiguration,
} from './hogfunctions/hogFunctionConfigurationLogic'
import { lemonToast } from '@posthog/lemon-ui'
import { EventType, PersonType } from '~/types'
import { groupsModel } from '~/models/groupsModel'

import type { hogFunctionReplayLogicType } from './hogFunctionReplayLogicType'

export const hogFunctionReplayLogic = kea<hogFunctionReplayLogicType>([
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'hogFunctionReplayLogic', key]),
    connect({
        values: [
            hogFunctionConfigurationLogic,
            ['configuration', 'matchingFilters', 'templateId'],
            groupsModel,
            ['groupTypes'],
        ],
    }),
    actions({
        changeDateRange: (after: string, before: string) => ({ after, before }),
    }),
    reducers({
        dateRange: [
            { after: '-7d', before: undefined },
            {
                changeDateRange: (_, { after, before }: { after: string; before: string }) => ({ after, before }),
            },
        ],
        retries: [
            [],
            {
                addRetry: (state, { retry }) => [...state.retries, retry],
            },
        ],
    }),
    selectors(({}) => ({
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
    loaders(({ values, props }) => ({
        events: [
            [],
            {
                loadEvents: async () => {
                    const response = await api.query(values.baseEventsQuery)
                    return response.results.map((row: any) => ({
                        event: row[0],
                        person: row[1],
                        retries: values.retries.filter((r: any) => r.eventId === row[0].uuid),
                    }))
                },
            },
        ],
        retries: [
            [],
            {
                retryHogFunction: async ({ event, person }: { event: EventType; person: PersonType }) => {
                    const globals = convertToHogFunctionInvocationGlobals(event, person)
                    globals.groups = {}
                    values.groupTypes.forEach((groupType, index) => {
                        const tuple = event?.[2 + index]
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

                    return [
                        {
                            eventId: event.uuid,
                            ...res,
                        },
                        ...values.retries,
                    ]
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        changeDateRange: () => {
            actions.loadEvents()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadEvents()
        },
    })),
])
