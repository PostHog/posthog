import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonTableColumns, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import api from '~/lib/api'
import { LogEntry, LogEntryLevel, LogEntryRequestParams } from '~/types'

import type { pipelineNodeLogsLogicType } from './pipelineNodeLogsLogicType'

export function LogLevelDisplay(level: LogEntryLevel): JSX.Element {
    let color: string | undefined
    switch (level) {
        case 'DEBUG':
            color = 'text-muted'
            break
        case 'LOG':
            color = 'text-text-3000'
            break
        case 'INFO':
            color = 'text-accent'
            break
        case 'WARNING':
        case 'WARN':
            color = 'text-warning'
            break
        case 'ERROR':
            color = 'text-danger'
            break
        default:
            break
    }
    return <span className={color}>{level}</span>
}

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARNING', 'ERROR']

export enum PipelineBackend {
    BatchExport = 'batch_export',
    Plugin = 'plugin',
}

export interface PipelineNodeLogsLogicProps {
    id: number | string
}

type PluginNodeId = {
    backend: PipelineBackend.Plugin
    id: number
}
type BatchExportNodeId = {
    backend: PipelineBackend.BatchExport
    id: string
}

export type PipelineNodeLimitedType = PluginNodeId | BatchExportNodeId

export const pipelineNodeLogsLogic = kea<pipelineNodeLogsLogicType>([
    props({} as PipelineNodeLogsLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'pipelineNodeLogsLogic', key]),
    connect(() => ({
        values: [teamLogic(), ['currentTeamId']],
    })),
    actions({
        setSelectedLogLevels: (levels: LogEntryLevel[]) => ({
            levels,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setInstanceId: (instanceId: string | null) => ({ instanceId }),
        clearBackgroundLogs: true,
        markLogsEnd: true,
    }),
    loaders(({ values, actions, cache }) => ({
        logs: [
            [] as LogEntry[],
            {
                loadLogs: async () => {
                    let results: LogEntry[] = []
                    const logParams: LogEntryRequestParams = {
                        search: values.searchTerm,
                        level: values.selectedLogLevelsForAPI.join(','),
                        limit: LOGS_PORTION_LIMIT,
                        instance_id: values.instanceId ?? undefined,
                    }

                    if (values.node.backend === PipelineBackend.BatchExport) {
                        const res = await api.batchExports.logs(values.node.id, logParams)
                        results = res.results
                    } else {
                        results = await api.pluginConfigs.logs(Number(values.node.id), logParams)
                    }

                    cache.disposables.add(() => {
                        const intervalId = setInterval(actions.pollBackgroundLogs, 5000)
                        return () => clearInterval(intervalId)
                    }, 'pollingInterval')
                    actions.clearBackgroundLogs()
                    return results
                },
                loadMoreLogs: async () => {
                    let results: LogEntry[]
                    const logParams: LogEntryRequestParams = {
                        search: values.searchTerm,
                        level: values.selectedLogLevels.join(','),
                        limit: LOGS_PORTION_LIMIT,
                        before: values.trailingEntry?.timestamp,
                        instance_id: values.instanceId ?? undefined,
                    }
                    if (values.node.backend === PipelineBackend.BatchExport) {
                        const res = await api.batchExports.logs(values.node.id, logParams)
                        results = res.results
                    } else {
                        results = await api.pluginConfigs.logs(Number(values.node.id), logParams)
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
                    const logParams: LogEntryRequestParams = {
                        search: values.searchTerm,
                        level: values.selectedLogLevels.join(','),
                        limit: LOGS_PORTION_LIMIT,
                        after: values.leadingEntry?.timestamp,
                        instance_id: values.instanceId ?? undefined,
                    }

                    if (values.node.backend === PipelineBackend.BatchExport) {
                        const res = await api.batchExports.logs(values.node.id, logParams)
                        results = res.results
                    } else {
                        results = await api.pluginConfigs.logs(Number(values.node.id), logParams)
                    }

                    return [...results, ...values.backgroundLogs]
                },
            },
        ],
    })),
    reducers({
        selectedLogLevels: [
            DEFAULT_LOG_LEVELS,
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
    selectors(({ actions, values }) => ({
        node: [
            (_, p) => [p.id],
            (id): PipelineNodeLimitedType => {
                if (typeof id === 'string') {
                    return { backend: PipelineBackend.BatchExport, id }
                }

                return { backend: PipelineBackend.Plugin, id }
            },
        ],
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
                        title: node.backend == PipelineBackend.BatchExport ? 'Run Id' : 'Source',
                        dataIndex: 'instance_id',
                        key: 'instance_id',
                        render: (instanceId: string) => (
                            <code className="whitespace-nowrap">
                                {node.backend !== PipelineBackend.Plugin ? (
                                    <Link
                                        subtle
                                        onClick={() => {
                                            if (values.instanceId === instanceId) {
                                                actions.setInstanceId(null)
                                            } else {
                                                actions.setInstanceId(instanceId)
                                            }
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
                        key: 'level',
                        dataIndex: 'level',
                        render: LogLevelDisplay,
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

        selectedLogLevelsForAPI: [
            (s) => [s.selectedLogLevels],
            (logLevels): LogEntryLevel[] => {
                const uniqueLevels = new Set(logLevels)
                if (uniqueLevels.has('WARN')) {
                    uniqueLevels.add('WARNING')
                }
                if (uniqueLevels.has('WARNING')) {
                    uniqueLevels.add('WARN')
                }
                return Array.from(uniqueLevels)
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
