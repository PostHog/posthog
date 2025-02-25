import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { delay } from 'lib/utils'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { HogFunctionInvocationGlobals } from '~/types'

import { GroupedLogEntry, logsViewerLogic, LogsViewerLogicProps } from './logsViewerLogic'

import type { hogFunctionLogsLogicType } from './hogFunctionLogsLogicType'

export type RetryInvocationState = 'pending' | 'success' | 'failure'

const loadEventGlobals = async (eventId: string): Promise<Pick<HogFunctionInvocationGlobals, 'event' | 'person'>> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: hogql`
            select uuid, distinct_id, event, timestamp, properties, person.id, person.properties 
            from events
            where uuid = ${eventId}
            limit 1`,
    }

    const response = await api.query(query, undefined, undefined, true)
    const [uuid, distinct_id, event, timestamp, properties, person_id, person_properties] = response.results[0]

    return {
        event: {
            uuid,
            distinct_id,
            event,
            properties: JSON.parse(properties),
            timestamp,
            url: '',
            elements_chain: '',
        },
        person: {
            id: person_id,
            properties: JSON.parse(person_properties),
            url: '',
            name: '',
        },
    }
}

export const hogFunctionLogsLogic = kea<hogFunctionLogsLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'logs', 'hogFunctionLogsLogic', key]),
    props({} as LogsViewerLogicProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ sourceType, sourceId }) => `${sourceType}:${sourceId}`),
    connect((props) => ({
        values: [logsViewerLogic(props), ['logs']],
        actions: [logsViewerLogic(props), ['addLogGroups', 'setRowExpanded']],
    })),
    actions({
        retryInvocation: (groupedLogEntry: GroupedLogEntry, eventId: string) => ({ groupedLogEntry, eventId }),
        retryInvocationSuccess: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retryInvocationFailure: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
    }),
    reducers({
        retries: [
            {} as Record<string, RetryInvocationState>,
            {
                retryInvocation: (state, { groupedLogEntry }) => {
                    return {
                        ...state,
                        [groupedLogEntry.instanceId]: 'pending',
                    }
                },

                retryInvocationSuccess: (state, { groupedLogEntry }) => {
                    return {
                        ...state,
                        [groupedLogEntry.instanceId]: 'success',
                    }
                },

                retryInvocationFailure: (state, { groupedLogEntry }) => {
                    return {
                        ...state,
                        [groupedLogEntry.instanceId]: 'failure',
                    }
                },
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        retryInvocation: async ({ groupedLogEntry, eventId }, breakpoint) => {
            await breakpoint(100)

            actions.setRowExpanded(groupedLogEntry.instanceId, true)
            await delay(1000)

            try {
                const globals = await loadEventGlobals(eventId)

                const res = await api.hogFunctions.createTestInvocation(props.sourceId, {
                    globals,
                    mock_async_functions: false,
                    configuration: {},
                })

                const existingLogGroup = values.logs.find((x) => x.instanceId === groupedLogEntry.instanceId)

                if (!existingLogGroup) {
                    throw new Error('No log group found')
                }

                const newLogGroup = {
                    ...existingLogGroup,
                    entries: [
                        ...existingLogGroup.entries,
                        ...res.logs.map((x) => ({
                            timestamp: dayjs(x.timestamp),
                            level: x.level.toUpperCase(),
                            message: x.message,
                        })),
                    ],
                }

                actions.addLogGroups([newLogGroup])

                lemonToast.success('Retry invocation success')
                await breakpoint(10)
                actions.retryInvocationSuccess(groupedLogEntry)
            } catch (e) {
                lemonToast.error('Retry invocation failed')
                await breakpoint(10)
                actions.retryInvocationFailure(groupedLogEntry)
            }
        },
    })),
])
