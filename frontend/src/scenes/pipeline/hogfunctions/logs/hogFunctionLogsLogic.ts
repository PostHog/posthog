import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { delay } from 'lib/utils'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { hogFunctionLogsLogicType } from './hogFunctionLogsLogicType'
import { GroupedLogEntry, logsViewerLogic, LogsViewerLogicProps } from './logsViewerLogic'

export type RetryInvocationState = 'pending' | 'success' | 'failure'

const loadClickhouseEvent = async (eventId: string): Promise<any> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: hogql`
            select uuid, distinct_id, event, timestamp, properties, elements_chain, person.id, person.properties, person.created_at 
            from events
            where uuid = ${eventId}
            limit 1`,
    }

    const response = await api.query(query, undefined, undefined, true)
    const [
        uuid,
        distinct_id,
        event,
        timestamp,
        properties,
        elements_chain,
        person_id,
        person_properties,
        person_created_at,
    ] = response.results[0]

    return {
        uuid,
        event,
        distinct_id,
        person_id,
        timestamp,
        properties,
        elements_chain,
        person_created_at,
        person_properties,
    }
}

export const hogFunctionLogsLogic = kea<hogFunctionLogsLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'logs', 'hogFunctionLogsLogic', key]),
    props({} as LogsViewerLogicProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ sourceType, sourceId }) => `${sourceType}:${sourceId}`),
    connect((props: LogsViewerLogicProps) => ({
        values: [logsViewerLogic(props), ['logs']],
        actions: [logsViewerLogic(props), ['addLogGroups', 'setRowExpanded']],
    })),
    actions({
        setSelectingMany: (selectingMany: boolean) => ({ selectingMany }),
        setSelectedForRetry: (selectedForRetry: Record<string, boolean>) => ({ selectedForRetry }),
        selectAllForRetry: true,
        retryInvocation: (groupedLogEntry: GroupedLogEntry, eventId: string) => ({ groupedLogEntry, eventId }),
        retryInvocationStarted: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retryInvocationSuccess: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retryInvocationFailure: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retrySelectedInvocations: true,
    }),
    reducers({
        selectingMany: [
            false,
            {
                setSelectingMany: (_, { selectingMany }) => selectingMany,
            },
        ],

        selectedForRetry: [
            {} as Record<string, boolean>,
            {
                setSelectedForRetry: (state, { selectedForRetry }) => {
                    const newState = { ...state }
                    Object.keys(selectedForRetry).forEach((key) => {
                        newState[key] = selectedForRetry[key]

                        if (!selectedForRetry[key]) {
                            delete newState[key]
                        }
                    })
                    return newState
                },

                setSelectingMany: (state, { selectingMany }) => {
                    return selectingMany ? state : {}
                },
            },
        ],

        retries: [
            {} as Record<string, RetryInvocationState>,
            {
                retryInvocationStarted: (state, { groupedLogEntry }) => {
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

            try {
                const res = await api.hogFunctions.createTestInvocation(props.sourceId, {
                    clickhouse_event: await loadClickhouseEvent(eventId),
                    mock_async_functions: false,
                    configuration: {
                        // For retries we don't care about filters
                        filters: {},
                    },
                    invocation_id: groupedLogEntry.instanceId,
                })

                const existingLogGroup = values.logs.find((x) => x.instanceId === groupedLogEntry.instanceId)

                if (!existingLogGroup) {
                    throw new Error('No log group found')
                }

                const newLogGroup: GroupedLogEntry = {
                    ...existingLogGroup,
                    entries: [
                        ...existingLogGroup.entries,
                        ...res.logs.map((x) => ({
                            timestamp: dayjs(x.timestamp),
                            level: x.level.toUpperCase() as LogEntryLevel,
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

        retrySelectedInvocations: async () => {
            await lemonToast.promise(
                (async () => {
                    const groupsToRetry = values.logs.filter((x) => values.selectedForRetry[x.instanceId])

                    for (const groupedLogEntry of groupsToRetry) {
                        actions.retryInvocationStarted(groupedLogEntry)
                    }

                    await delay(1000) // TODO: Remove

                    for (const groupedLogEntry of groupsToRetry) {
                        actions.retryInvocationFailure(groupedLogEntry)
                    }

                    actions.setSelectingMany(false)
                })(),
                {
                    success: 'Retries complete!',
                    error: 'Retry failed!',
                    pending: 'Retrying...',
                }
            )
        },

        selectAllForRetry: async () => {
            actions.setSelectingMany(true)

            for (const groupedLogEntry of values.logs) {
                actions.setSelectedForRetry({
                    [groupedLogEntry.instanceId]: true,
                })
            }
        },
    })),
])
