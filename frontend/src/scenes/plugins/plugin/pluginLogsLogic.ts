import { kea } from 'kea'
import api from '~/lib/api'
import { PluginLogEntry } from '~/types'
import { teamLogic } from '../../teamLogic'
import { pluginLogsLogicType } from './pluginLogsLogicType'

export interface PluginLogsProps {
    pluginConfigId: number
}

export const LOGS_PORTION_LIMIT = 50

export const pluginLogsLogic = kea<pluginLogsLogicType<PluginLogsProps>>({
    props: {} as PluginLogsProps,
    key: ({ pluginConfigId }: PluginLogsProps) => pluginConfigId,
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },

    actions: {
        clearPluginLogsBackground: true,
        markLogsEnd: true,
    },

    loaders: ({ props: { pluginConfigId }, values, actions, cache }) => ({
        pluginLogs: {
            __default: [] as PluginLogEntry[],
            loadPluginLogsInitially: async () => {
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/plugin_configs/${pluginConfigId}/logs?limit=${LOGS_PORTION_LIMIT}`
                )
                cache.pollingInterval = setInterval(actions.loadPluginLogsBackgroundPoll, 2000)
                actions.clearPluginLogsBackground()
                return response.results
            },
            loadPluginLogsSearch: async (searchTerm: string) => {
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/plugin_configs/${pluginConfigId}/logs?limit=${LOGS_PORTION_LIMIT}&search=${searchTerm}`
                )
                actions.clearPluginLogsBackground()
                return response.results
            },
            loadPluginLogsMore: async () => {
                const before = values.trailingEntry ? '&before=' + values.trailingEntry.timestamp : ''
                const search = values.searchTerm ? `&search=${values.searchTerm}` : ''
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/plugin_configs/${pluginConfigId}/logs?limit=${LOGS_PORTION_LIMIT}${before}${search}`
                )
                if (response.count < LOGS_PORTION_LIMIT) {
                    actions.markLogsEnd()
                }
                return [...values.pluginLogs, ...response.results]
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
                const after = values.leadingEntry ? 'after=' + values.leadingEntry.timestamp : ''
                const search = values.searchTerm ? `search=${values.searchTerm}` : ''
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/plugin_configs/${pluginConfigId}/logs?${[after, search]
                        .filter(Boolean)
                        .join('&')}`
                )
                return [...response.results, ...values.pluginLogsBackground]
            },
        },
    }),

    reducers: {
        pluginLogsBackground: [
            [] as PluginLogEntry[],
            {
                clearPluginLogsBackground: () => [],
            },
        ],
        searchTerm: [
            '',
            {
                loadPluginLogsSearch: (_, searchTerm) => searchTerm || '',
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                loadPluginLogsInitiallySuccess: (_, { pluginLogs }) => pluginLogs.length >= LOGS_PORTION_LIMIT,
                markLogsEnd: () => false,
            },
        ],
    },

    selectors: ({ selectors }) => ({
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
    }),

    events: ({ actions, cache }) => ({
        afterMount: () => {
            actions.loadPluginLogsInitially()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    }),
})
