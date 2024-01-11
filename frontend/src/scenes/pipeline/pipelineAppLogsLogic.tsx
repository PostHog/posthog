import { LemonTableColumns } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { DestinationTypeKind } from 'scenes/pipeline/destinationsLogic'
import { pipelineAppLogic } from 'scenes/pipeline/pipelineAppLogic'

import api from '~/lib/api'
import { BatchExportLogEntry, PipelineTabs, PluginLogEntry } from '~/types'

import { teamLogic } from '../teamLogic'
import type { pipelineAppLogsLogicType } from './pipelineAppLogsLogicType'
import { LogLevelDisplay, logLevelsToTypeFilters, LogTypeDisplay } from './utils'

type LogEntry = BatchExportLogEntry | PluginLogEntry

export enum PipelineAppLogLevel {
    Debug = 'DEBUG',
    Log = 'LOG',
    Info = 'INFO',
    Warning = 'WARNING',
    Error = 'ERROR',
}

export interface PipelineAppLogsProps {
    id: number | string
    kind: PipelineTabs // This needs to be props passed for connecting to pipelineAppLogic
}

export const pipelineAppLogsLogic = kea<pipelineAppLogsLogicType>([
    props({} as PipelineAppLogsProps),
    key(({ id }: PipelineAppLogsProps) => id),
    path((key) => ['scenes', 'pipeline', 'pipelineAppLogsLogic', key]),
    connect((props: PipelineAppLogsProps) => ({
        values: [teamLogic, ['currentTeamId'], pipelineAppLogic(props), ['appType']],
    })),
    actions({
        setSelectedLogLevels: (levels: PipelineAppLogLevel[]) => ({
            levels,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearBackgroundLogs: true,
        markLogsEnd: true,
    }),
    loaders(({ props: { id }, values, actions, cache }) => ({
        logs: {
            __default: [] as LogEntry[],
            loadLogs: async () => {
                let results: LogEntry[]
                if (values.appType === DestinationTypeKind.BatchExport) {
                    results = await api.batchExportLogs.search(
                        id as string,
                        values.currentTeamId,
                        values.searchTerm,
                        values.selectedLogLevels
                    )
                } else {
                    results = await api.pluginLogs.search(
                        id as number,
                        values.currentTeamId,
                        values.searchTerm,
                        logLevelsToTypeFilters(values.selectedLogLevels)
                    )
                }

                if (!cache.pollingInterval) {
                    cache.pollingInterval = setInterval(actions.pollBackgroundLogs, 5000)
                }
                actions.clearBackgroundLogs()
                return results
            },
            loadMoreLogs: async () => {
                const results = await api.pluginLogs.search(
                    id,
                    values.currentTeamId,
                    values.searchTerm,
                    logLevelsToTypeFilters(values.selectedLogLevels),
                    values.trailingEntry
                )

                if (results.length < LOGS_PORTION_LIMIT) {
                    actions.markLogsEnd()
                }
                return [...values.logs, ...results]
            },
            revealBackground: () => {
                const newArray = [...values.backgroundLogs, ...values.logs]
                actions.clearBackgroundLogs()
                return newArray
            },
        },
        backgroundLogs: {
            __default: [] as LogEntry[],
            pollBackgroundLogs: async () => {
                // we fetch new logs in the background and allow the user to expand
                // them into the array of visible logs
                if (values.logsLoading) {
                    return values.backgroundLogs
                }

                const results = await api.pluginLogs.search(
                    id,
                    values.currentTeamId,
                    values.searchTerm,
                    logLevelsToTypeFilters(values.selectedLogLevels),
                    null,
                    values.leadingEntry
                )

                return [...results, ...values.backgroundLogs]
            },
        },
    })),
    reducers({
        selectedLogLevels: [
            Object.values(PipelineAppLogLevel).filter((level) => level !== 'DEBUG'),
            {
                setSelectedLogLevels: (_, { levels }) => levels,
            },
        ],
        backgroundLogs: [
            [] as PluginLogEntry[],
            {
                clearBackgroundLogs: () => [],
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                loadLogsSuccess: (_, { logs }) => logs.length >= LOGS_PORTION_LIMIT,
                markLogsEnd: () => false,
            },
        ],
    }),
    selectors({
        leadingEntry: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: LogEntry[], backgroundLogs: LogEntry[]): LogEntry | null => {
                if (backgroundLogs.length) {
                    return backgroundLogs[0]
                }
                if (logs.length) {
                    return logs[0]
                }
                return null
            },
        ],
        trailingEntry: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: LogEntry[], backgroundLogs: LogEntry[]): LogEntry | null => {
                if (logs.length) {
                    return logs[logs.length - 1]
                }
                if (backgroundLogs.length) {
                    return backgroundLogs[backgroundLogs.length - 1]
                }
                return null
            },
        ],
        columns: [
            (s) => [s.appType],
            (appType): LemonTableColumns<Record<string, any>> => {
                return [
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        render: (timestamp: string) => dayjs(timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
                    },
                    {
                        title: appType === DestinationTypeKind.BatchExport ? 'Run Id' : 'Source',
                        dataIndex: appType === DestinationTypeKind.BatchExport ? 'run_id' : 'source',
                        key: appType === DestinationTypeKind.BatchExport ? 'run_id' : 'source',
                    },
                    {
                        title: 'Level',
                        key: appType === DestinationTypeKind.BatchExport ? 'level' : 'type',
                        dataIndex: appType === DestinationTypeKind.BatchExport ? 'level' : 'type',
                        render: appType === DestinationTypeKind.BatchExport ? LogLevelDisplay : LogTypeDisplay,
                    },
                    {
                        title: 'Message',
                        key: 'message',
                        dataIndex: 'message',
                        render: (message: string) => <code className="whitespace-pre-wrap">{message}</code>,
                    },
                ]
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSelectedLogLevels: () => {
            actions.loadLogs()
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm) {
                await breakpoint(1000)
            }
            actions.loadLogs()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadLogs()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])
