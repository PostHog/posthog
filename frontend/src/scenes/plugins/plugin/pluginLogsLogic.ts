import { kea } from 'kea'
import api from '~/lib/api'
import { PluginLogEntry } from '~/types'
import { pluginLogsLogicType } from './pluginLogsLogicType'

export interface PluginLogsProps {
    organizationId: string
    teamId: number
    pluginId: number
}

export const LOGS_PORTION_LIMIT = 50

export const pluginLogsLogic = kea<pluginLogsLogicType & { props: PluginLogsProps }>({
    key: ({ organizationId, teamId, pluginId }) => `${organizationId}-${teamId}-${pluginId}`,

    actions: {
        clearPluginLogsBackground: true,
    },

    loaders: ({ props: { organizationId, teamId, pluginId }, values, actions, cache }) => ({
        pluginLogs: {
            __default: [] as PluginLogEntry[],
            loadPluginLogsAnew: async (searchTerm = '') => {
                const search = searchTerm ? `&search=${searchTerm}` : ''
                const limit = `&limit=${LOGS_PORTION_LIMIT}`
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}${search}${limit}`
                )
                cache.pollingInterval = setInterval(actions.loadPluginLogsBackgroundPoll, 2000)
                actions.clearPluginLogsBackground()
                return response.results
            },
            loadPluginLogsMore: async () => {
                const length = values.pluginLogs.length
                const before = length ? '&before=' + values.pluginLogs[length - 1].timestamp : ''
                const search = values.searchTerm ? `&search=${values.searchTerm}` : ''
                const limit = `&limit=${LOGS_PORTION_LIMIT}`
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}${before}${search}${limit}`
                )
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
                const after = values.leadingEntry ? '&after=' + values.leadingEntry.timestamp : ''
                const search = values.searchTerm ? `&search=${values.searchTerm}` : ''
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}${after}${search}`
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
                loadPluginLogsAnew: (_, searchTerm) => searchTerm || '',
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                loadPluginLogsAnewSuccess: (_, { pluginLogs }) => pluginLogs.length >= LOGS_PORTION_LIMIT,
                loadPluginLogsMoreSuccess: (_, { pluginLogs }) => pluginLogs.length >= LOGS_PORTION_LIMIT,
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
    }),

    events: ({ actions, cache }) => ({
        afterMount: () => {
            actions.loadPluginLogsAnew()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    }),
})
