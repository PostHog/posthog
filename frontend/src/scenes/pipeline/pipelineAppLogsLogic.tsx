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
    path((key) => ['scenes', 'plugins', 'plugin', 'pluginLogsLogic', key]),
    connect((props: PipelineAppLogsProps) => ({
        values: [teamLogic, ['currentTeamId'], pipelineAppLogic(props), ['appType']],
    })),
    actions({
        clearPluginLogsBackground: true,
        markLogsEnd: true,
        setSelectedLogLevels: (levels: PipelineAppLogLevel[]) => ({
            levels,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ props: { id }, values, actions, cache }) => ({
        pluginLogs: {
            __default: [] as PluginLogEntry[] | BatchExportLogEntry[],
            loadPluginLogs: async () => {
                let results: PluginLogEntry[] | BatchExportLogEntry[]
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
                    cache.pollingInterval = setInterval(actions.loadPluginLogsBackgroundPoll, 2000)
                }
                actions.clearPluginLogsBackground()
                return results
            },
            loadPluginLogsMore: async () => {
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
                return [...values.pluginLogs, ...results]
            },
            revealBackground: () => {
                const newArray = [...values.pluginLogsBackground, ...values.pluginLogs]
                actions.clearPluginLogsBackground()
                return newArray
            },
        },
        pluginLogsBackground: {
            __default: [] as PluginLogEntry[],
            loadPluginLogsBackgroundPoll: async () => {
                if (values.pluginLogsLoading) {
                    return values.pluginLogsBackground
                }

                const results = await api.pluginLogs.search(
                    id,
                    values.currentTeamId,
                    values.searchTerm,
                    logLevelsToTypeFilters(values.selectedLogLevels),
                    null,
                    values.leadingEntry
                )

                return [...results, ...values.pluginLogsBackground]
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
        pluginLogsBackground: [
            [] as PluginLogEntry[],
            {
                clearPluginLogsBackground: () => [],
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
                loadPluginLogsSuccess: (_, { pluginLogs }) => pluginLogs.length >= LOGS_PORTION_LIMIT,
                markLogsEnd: () => false,
            },
        ],
    }),
    selectors(({ selectors }) => ({
        leadingEntry: [
            () => [selectors.pluginLogs, selectors.pluginLogsBackground],
            (pluginLogs: PluginLogEntry[], pluginLogsBackground: PluginLogEntry[]): PluginLogEntry | null => {
                if (pluginLogsBackground.length) {
                    return pluginLogsBackground[0]
                }
                if (pluginLogs.length) {
                    return pluginLogs[0]
                }
                return null
            },
        ],
        trailingEntry: [
            () => [selectors.pluginLogs, selectors.pluginLogsBackground],
            (pluginLogs: PluginLogEntry[], pluginLogsBackground: PluginLogEntry[]): PluginLogEntry | null => {
                if (pluginLogs.length) {
                    return pluginLogs[pluginLogs.length - 1]
                }
                if (pluginLogsBackground.length) {
                    return pluginLogsBackground[pluginLogsBackground.length - 1]
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
    })),
    listeners(({ actions }) => ({
        setSelectedLogLevels: () => {
            actions.loadPluginLogs()
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm) {
                await breakpoint(1000)
            }
            actions.loadPluginLogs()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadPluginLogs()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])
