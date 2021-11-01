import { kea } from 'kea'
import api from '~/lib/api'
import { PluginLogEntry } from '~/types'
import { teamLogic } from '../../teamLogic'
import { pluginLogsLogicType } from './pluginLogsLogicType'
import { CheckboxValueType } from 'antd/lib/checkbox/Group'

export interface PluginLogsProps {
    pluginConfigId: number
}

export const LOGS_PORTION_LIMIT = 50

const makeLogsAPICall = async (
    pluginConfigId: number,
    currentTeamId: number | null,
    searchTerm: string,
    typeFilters: CheckboxValueType[],
    trailingEntry: PluginLogEntry | null = null,
    leadingEntry: PluginLogEntry | null = null
): Promise<PluginLogEntry[]> => {
    const type_filters =
        typeFilters && typeFilters.length > 0 ? `&type_filter=${typeFilters.join('&type_filter=')}` : ''
    const search = searchTerm ? `&search=${searchTerm}` : ''
    const before = trailingEntry ? '&before=' + trailingEntry.timestamp : ''
    const after = leadingEntry ? '&after=' + leadingEntry.timestamp : ''

    const response = await api.get(
        `api/projects/${currentTeamId}/plugin_configs/${pluginConfigId}/logs?limit=${LOGS_PORTION_LIMIT}${before}${after}${search}${type_filters}`
    )

    return response.results
}

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
                const results = await makeLogsAPICall(
                    pluginConfigId,
                    values.currentTeamId,
                    searchTerm,
                    values.typeFilters
                )
                actions.clearPluginLogsBackground()
                return results
            },
            loadPluginLogsTypes: async (typeFilters: CheckboxValueType[]) => {
                const results = await makeLogsAPICall(
                    pluginConfigId,
                    values.currentTeamId,
                    values.searchTerm,
                    typeFilters
                )
                actions.clearPluginLogsBackground()
                return results
            },
            loadPluginLogsMore: async () => {
                const results = await makeLogsAPICall(
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

                const results = await makeLogsAPICall(
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
        typeFilters: [
            [] as CheckboxValueType[],
            {
                loadPluginLogsTypes: (_, types) => types || [],
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
