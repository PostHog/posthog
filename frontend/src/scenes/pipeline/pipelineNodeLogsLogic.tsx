import { TZLabel } from '@posthog/apps-common'
import { LemonTableColumns, Link } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { pipelineNodeLogic, PipelineNodeLogicProps } from 'scenes/pipeline/pipelineNodeLogic'

import api from '~/lib/api'
import { BatchExportLogEntry, PluginLogEntry } from '~/types'

import { teamLogic } from '../teamLogic'
import type { pipelineNodeLogsLogicType } from './pipelineNodeLogsLogicType'
import { PipelineBackend } from './types'
import { LogLevelDisplay, logLevelsToTypeFilters, LogTypeDisplay } from './utils'

export type LogEntry = BatchExportLogEntry | PluginLogEntry

export enum PipelineLogLevel {
    Debug = 'DEBUG',
    Log = 'LOG',
    Info = 'INFO',
    Warning = 'WARNING',
    Error = 'ERROR',
}

export const pipelineNodeLogsLogic = kea<pipelineNodeLogsLogicType>([
    props({} as PipelineNodeLogicProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'pipelineNodeLogsLogic', key]),
    connect((props: PipelineNodeLogicProps) => ({
        values: [teamLogic(), ['currentTeamId'], pipelineNodeLogic(props), ['node']],
    })),
    actions({
        setSelectedLogLevels: (levels: PipelineLogLevel[]) => ({
            levels,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setInstanceId: (instanceId: string | null) => ({ instanceId }),
        clearBackgroundLogs: true,
        markLogsEnd: true,
    }),
    loaders(({ props: { id }, values, actions, cache }) => ({
        logs: [
            [] as LogEntry[],
            {
                loadLogs: async () => {
                    let results: LogEntry[]
                    if (values.node.backend === PipelineBackend.BatchExport) {
                        results = await api.batchExportLogs.search(
                            values.node.id,
                            values.searchTerm,
                            values.selectedLogLevels
                        )
                    } else if (values.node.backend === PipelineBackend.HogFunction) {
                        const res = await api.hogFunctions.searchLogs(values.node.id, {
                            search: values.searchTerm,
                            levels: values.selectedLogLevels,
                            limit: LOGS_PORTION_LIMIT,
                            instance_id: values.instanceId,
                        })

                        results = res.results
                    } else {
                        results = await api.pluginLogs.search(
                            values.node.id,
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
                    if (values.node.backend === PipelineBackend.BatchExport) {
                        results = await api.batchExportLogs.search(
                            id as string,
                            values.searchTerm,
                            values.selectedLogLevels,
                            values.trailingEntry as BatchExportLogEntry | null
                        )
                    } else if (values.node.backend === PipelineBackend.HogFunction) {
                        const res = await api.hogFunctions.searchLogs(values.node.id, {
                            search: values.searchTerm,
                            levels: values.selectedLogLevels,
                            limit: LOGS_PORTION_LIMIT,
                            before: values.trailingEntry?.timestamp,
                            instance_id: values.instanceId,
                        })

                        results = res.results
                    } else {
                        results = await api.pluginLogs.search(
                            id as number,
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
        ],
        backgroundLogs: [
            [] as LogEntry[],
            {
                pollBackgroundLogs: async () => {
                    // we fetch new logs in the background and allow the user to expand
                    // them into the array of visible logs
                    if (values.logsLoading) {
                        return values.backgroundLogs
                    }

                    let results: LogEntry[]
                    if (values.node.backend === PipelineBackend.BatchExport) {
                        results = await api.batchExportLogs.search(
                            id as string,
                            values.searchTerm,
                            values.selectedLogLevels,
                            null,
                            values.leadingEntry as BatchExportLogEntry | null
                        )
                    } else if (values.node.backend === PipelineBackend.HogFunction) {
                        const res = await api.hogFunctions.searchLogs(values.node.id, {
                            search: values.searchTerm,
                            levels: values.selectedLogLevels,
                            limit: LOGS_PORTION_LIMIT,
                            after: values.leadingEntry?.timestamp,
                            instance_id: values.instanceId,
                        })

                        results = res.results
                    } else {
                        results = await api.pluginLogs.search(
                            id as number,
                            values.searchTerm,
                            logLevelsToTypeFilters(values.selectedLogLevels),
                            null,
                            values.leadingEntry as PluginLogEntry | null
                        )
                    }

                    return [...results, ...values.backgroundLogs]
                },
            },
        ],
    })),
    reducers({
        selectedLogLevels: [
            Object.values(PipelineLogLevel).filter((level) => level !== 'DEBUG'),
            {
                setSelectedLogLevels: (_, { levels }) => levels,
            },
        ],
        backgroundLogs: [
            [] as LogEntry[],
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
        instanceId: [
            null as null | string,
            {
                setInstanceId: (_, { instanceId }) => instanceId,
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
    selectors(({ actions }) => ({
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
            (s) => [s.node],
            (node): LemonTableColumns<LogEntry> => {
                return [
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        sorter: (a: LogEntry, b: LogEntry) => dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
                        render: (timestamp: string) => <TZLabel time={timestamp} />,
                        width: 0,
                    },
                    {
                        width: 0,
                        title:
                            node.backend == PipelineBackend.HogFunction
                                ? 'Invocation'
                                : node.backend == PipelineBackend.BatchExport
                                ? 'Run Id'
                                : 'Source',
                        dataIndex:
                            node.backend == PipelineBackend.HogFunction
                                ? 'instance_id'
                                : node.backend == PipelineBackend.BatchExport
                                ? 'run_id'
                                : 'source',
                        key:
                            node.backend == PipelineBackend.HogFunction
                                ? 'instance_id'
                                : node.backend == PipelineBackend.BatchExport
                                ? 'run_id'
                                : 'source',

                        render: (instanceId: string) => (
                            <code className="whitespace-nowrap">
                                {node.backend === PipelineBackend.HogFunction ? (
                                    <Link
                                        subtle
                                        onClick={() => {
                                            actions.setInstanceId(instanceId)
                                        }}
                                    >
                                        {instanceId}
                                    </Link>
                                ) : (
                                    instanceId
                                )}
                            </code>
                        ),
                    },
                    {
                        width: 100,
                        title: 'Level',
                        key:
                            node.backend == PipelineBackend.HogFunction
                                ? 'level'
                                : node.backend == PipelineBackend.BatchExport
                                ? 'level'
                                : 'type',
                        dataIndex:
                            node.backend == PipelineBackend.HogFunction
                                ? 'level'
                                : node.backend == PipelineBackend.BatchExport
                                ? 'level'
                                : 'type',
                        render:
                            node.backend == PipelineBackend.HogFunction
                                ? LogLevelDisplay
                                : node.backend == PipelineBackend.BatchExport
                                ? LogLevelDisplay
                                : LogTypeDisplay,
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
    })),
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
        setInstanceId: async () => {
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
