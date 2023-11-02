import { loaders } from 'kea-loaders'
import { kea, props, key, path, connect, actions, reducers, selectors, listeners, events } from 'kea'
import api from '~/lib/api'
import { PluginLogEntry, PluginLogEntryType } from '~/types'
import { teamLogic } from '../../teamLogic'
import type { pluginLogsLogicType } from './pluginLogsLogicType'
import { CheckboxValueType } from 'antd/lib/checkbox/Group'

export interface PluginLogsProps {
    pluginConfigId: number
}

export const LOGS_PORTION_LIMIT = 50

export const pluginLogsLogic = kea<pluginLogsLogicType>([
    props({} as PluginLogsProps),
    key(({ pluginConfigId }: PluginLogsProps) => pluginConfigId),
    path((key) => ['scenes', 'plugins', 'plugin', 'pluginLogsLogic', key]),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        clearPluginLogsBackground: true,
        markLogsEnd: true,
        setPluginLogsTypes: (typeFilters: CheckboxValueType[]) => ({
            typeFilters,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ props: { pluginConfigId }, values, actions, cache }) => ({
        pluginLogs: {
            __default: [] as PluginLogEntry[],
            loadPluginLogs: async () => {
                const results = await api.pluginLogs.search(
                    pluginConfigId,
                    values.currentTeamId,
                    values.searchTerm,
                    values.typeFilters
                )
                if (!cache.pollingInterval) {
                    cache.pollingInterval = setInterval(actions.loadPluginLogsBackgroundPoll, 2000)
                }
                actions.clearPluginLogsBackground()
                return results
            },
            loadPluginLogsMore: async () => {
                const results = await api.pluginLogs.search(
                    pluginConfigId,
                    values.currentTeamId,
                    values.searchTerm,
                    values.typeFilters,
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
                    pluginConfigId,
                    values.currentTeamId,
                    values.searchTerm,
                    values.typeFilters,
                    null,
                    values.leadingEntry
                )

                return [...results, ...values.pluginLogsBackground]
            },
        },
    })),
    reducers({
        pluginLogsTypes: [
            Object.values(PluginLogEntryType).filter((type) => type !== 'DEBUG'),
            {
                setPluginLogsTypes: (_, { typeFilters }) => typeFilters.map((tf) => tf as PluginLogEntryType),
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
        typeFilters: [
            Object.values(PluginLogEntryType).filter((type) => type !== 'DEBUG') as CheckboxValueType[],
            {
                setPluginLogsTypes: (_, { typeFilters }) => typeFilters || [],
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
    })),
    listeners(({ actions }) => ({
        setPluginLogsTypes: () => {
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
