import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CheckboxValueType } from '~/lib/api'
import { LogEntry, LogEntryLevel } from '~/types'

import type { batchExportLogsLogicType } from './batchExportLogsLogicType'

export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['INFO', 'WARNING', 'LOG', 'ERROR']
export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', ...DEFAULT_LOG_LEVELS]

export interface BatchExportLogsProps {
    batchExportId: string
}

export const LOGS_PORTION_LIMIT = 50

export const batchExportLogsLogic = kea<batchExportLogsLogicType>([
    props({} as BatchExportLogsProps),
    key(({ batchExportId }: BatchExportLogsProps) => batchExportId),
    path((batchExportId) => ['scenes', 'batch_exports', 'batchExportLogsLogic', batchExportId]),
    actions({
        clearBatchExportLogsBackground: true,
        markLogsEnd: true,
        setBatchExportLogsTypes: (typeFilters: CheckboxValueType[]) => ({
            typeFilters,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ props: { batchExportId }, values, actions, cache }) => ({
        batchExportLogs: {
            __default: [] as LogEntry[],
            loadBatchExportLogs: async () => {
                const response = await api.batchExports.logs(batchExportId, {
                    search: values.searchTerm,
                    level: values.typeFilters.join(','),
                })

                if (!cache.pollingInterval) {
                    cache.pollingInterval = setInterval(actions.loadBatchExportLogsBackgroundPoll, 2000)
                }
                actions.clearBatchExportLogsBackground()
                return response.results
            },
            loadBatchExportLogsMore: async () => {
                const response = await api.batchExports.logs(batchExportId, {
                    search: values.searchTerm,
                    level: values.typeFilters.join(','),
                    before: values.trailingEntry?.timestamp,
                })

                if (response.results.length < LOGS_PORTION_LIMIT) {
                    actions.markLogsEnd()
                }
                return [...values.batchExportLogs, ...response.results]
            },
            revealBackground: () => {
                const newArray = [...values.batchExportLogsBackground, ...values.batchExportLogs]
                actions.clearBatchExportLogsBackground()
                return newArray
            },
        },
        batchExportLogsBackground: {
            __default: [] as LogEntry[],
            loadBatchExportLogsBackgroundPoll: async () => {
                if (values.batchExportLogsLoading) {
                    return values.batchExportLogsBackground
                }

                const response = await api.batchExports.logs(batchExportId, {
                    search: values.searchTerm,
                    level: values.typeFilters.join(','),
                    after: values.leadingEntry?.timestamp,
                })

                return [...response.results, ...values.batchExportLogsBackground]
            },
        },
    })),
    reducers({
        batchExportLogsTypes: [
            DEFAULT_LOG_LEVELS,
            {
                setBatchExportLogsTypes: (_, { typeFilters }) => typeFilters.map((tf) => tf as LogEntryLevel),
            },
        ],
        batchExportLogsBackground: [
            [] as LogEntry[],
            {
                clearBatchExportLogsBackground: () => [],
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        typeFilters: [
            DEFAULT_LOG_LEVELS as CheckboxValueType[],
            {
                setBatchExportLogsTypes: (_, { typeFilters }) => typeFilters || [],
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                loadBatchExportLogsSuccess: (_, { batchExportLogs }) => batchExportLogs.length >= LOGS_PORTION_LIMIT,
                markLogsEnd: () => false,
            },
        ],
    }),
    selectors(() => ({
        leadingEntry: [
            (s) => [s.batchExportLogs, s.batchExportLogsBackground],
            (batchExportLogs, batchExportLogsBackground): LogEntry | null => {
                if (batchExportLogsBackground.length) {
                    return batchExportLogsBackground[0]
                }
                if (batchExportLogs.length) {
                    return batchExportLogs[0]
                }
                return null
            },
        ],
        trailingEntry: [
            (s) => [s.batchExportLogs, s.batchExportLogsBackground],
            (batchExportLogs, batchExportLogsBackground): LogEntry | null => {
                if (batchExportLogs.length) {
                    return batchExportLogs[batchExportLogs.length - 1]
                }
                if (batchExportLogsBackground.length) {
                    return batchExportLogsBackground[batchExportLogsBackground.length - 1]
                }
                return null
            },
        ],
    })),
    listeners(({ actions }) => ({
        setBatchExportLogsTypes: () => {
            actions.loadBatchExportLogs()
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm) {
                await breakpoint(1000)
            }
            actions.loadBatchExportLogs()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadBatchExportLogs()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])
