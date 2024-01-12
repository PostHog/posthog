import { LemonTableColumns } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { PipelineAppBackend } from 'scenes/pipeline/destinationsLogic'
import { pipelineAppLogic, PipelineAppLogicProps } from 'scenes/pipeline/pipelineAppLogic'

import api from '~/lib/api'
import { BatchExportLogEntry, PluginLogEntry } from '~/types'

import { teamLogic } from '../teamLogic'
import type { pipelineAppLogsLogicType } from './pipelineAppLogsLogicType'
import { LogLevelDisplay, logLevelsToTypeFilters, LogTypeDisplay } from './utils'

export type LogEntry = BatchExportLogEntry | PluginLogEntry

export enum PipelineAppLogLevel {
    Debug = 'DEBUG',
    Log = 'LOG',
    Info = 'INFO',
    Warning = 'WARNING',
    Error = 'ERROR',
}

export const pipelineAppLogsLogic = kea<pipelineAppLogsLogicType>([
    props({} as PipelineAppLogicProps),
    key(({ id }: PipelineAppLogicProps) => id),
    path((key) => ['scenes', 'pipeline', 'pipelineAppLogsLogic', key]),
    connect((props: PipelineAppLogicProps) => ({
        values: [teamLogic(), ['currentTeamId'], pipelineAppLogic(props), ['appBackend']],
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
            __default: [] as PluginLogEntry[] | BatchExportLogEntry[],
            loadLogs: async () => {
                let results: LogEntry[]
                if (values.appBackend === PipelineAppBackend.BatchExport) {
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
                let results: LogEntry[]
                if (values.appBackend === PipelineAppBackend.BatchExport) {
                    results = await api.batchExportLogs.search(
                        id as string,
                        values.currentTeamId,
                        values.searchTerm,
                        values.selectedLogLevels,
                        values.trailingEntry as BatchExportLogEntry | null
                    )
                } else {
                    results = await api.pluginLogs.search(
                        id as number,
                        values.currentTeamId,
                        values.searchTerm,
                        logLevelsToTypeFilters(values.selectedLogLevels),
                        values.trailingEntry as PluginLogEntry | null
                    )
                }

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
            __default: [] as PluginLogEntry[] | BatchExportLogEntry[],
            pollBackgroundLogs: async () => {
                // we fetch new logs in the background and allow the user to expand
                // them into the array of visible logs
                if (values.logsLoading) {
                    return values.backgroundLogs
                }

                let results: LogEntry[]
                if (values.appBackend === PipelineAppBackend.BatchExport) {
                    results = await api.batchExportLogs.search(
                        id as string,
                        values.currentTeamId,
                        values.searchTerm,
                        values.selectedLogLevels,
                        null,
                        values.leadingEntry as BatchExportLogEntry | null
                    )
                } else {
                    results = await api.pluginLogs.search(
                        id as number,
                        values.currentTeamId,
                        values.searchTerm,
                        logLevelsToTypeFilters(values.selectedLogLevels),
                        null,
                        values.leadingEntry as PluginLogEntry | null
                    )
                }

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
            [] as PluginLogEntry[] | BatchExportLogEntry[],
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
            (s) => [s.appBackend],
            (appBackend): LemonTableColumns<LogEntry> => {
                return [
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        render: (timestamp: string) => dayjs(timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
                    },
                    {
                        title: appBackend === PipelineAppBackend.BatchExport ? 'Run Id' : 'Source',
                        dataIndex: appBackend === PipelineAppBackend.BatchExport ? 'run_id' : 'source',
                        key: appBackend === PipelineAppBackend.BatchExport ? 'run_id' : 'source',
                    },
                    {
                        title: 'Level',
                        key: appBackend === PipelineAppBackend.BatchExport ? 'level' : 'type',
                        dataIndex: appBackend === PipelineAppBackend.BatchExport ? 'level' : 'type',
                        render: appBackend === PipelineAppBackend.BatchExport ? LogLevelDisplay : LogTypeDisplay,
                    },
                    {
                        title: 'Message',
                        key: 'message',
                        dataIndex: 'message',
                        render: (message: string) => <code className="whitespace-pre-wrap">{message}</code>,
                    },
                ] as LemonTableColumns<LogEntry>
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
