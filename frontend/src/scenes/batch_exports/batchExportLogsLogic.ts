import { loaders } from 'kea-loaders'
import { kea, props, key, path, connect, actions, reducers, selectors, listeners, events } from 'kea'
import api from '~/lib/api'
import { BatchExportLogEntryLevel, BatchExportLogEntry } from '~/types'
import { CheckboxValueType } from 'antd/lib/checkbox/Group'
import { teamLogic } from 'scenes/teamLogic'

import type { batchExportLogsLogicType } from './batchExportLogsLogicType'

export interface BatchExportLogsProps {
    batchExportId: string
}

export const LOGS_PORTION_LIMIT = 50

export const batchExportLogsLogic = kea<batchExportLogsLogicType>([
    props({} as BatchExportLogsProps),
    key(({ batchExportId }: BatchExportLogsProps) => batchExportId),
    path((batchExportId) => ['scenes', 'batch_exports', 'batchExportLogsLogic', batchExportId]),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
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
            __default: [] as BatchExportLogEntry[],
            loadBatchExportLogs: async () => {
                const results = await api.batchExportLogs.search(
                    batchExportId,
                    values.currentTeamId,
                    values.searchTerm,
                    values.typeFilters
                )

                if (!cache.pollingInterval) {
                    cache.pollingInterval = setInterval(actions.loadBatchExportLogsBackgroundPoll, 2000)
                }
                actions.clearBatchExportLogsBackground()
                return results
            },
            loadBatchExportLogsMore: async () => {
                const results = await api.batchExportLogs.search(
                    batchExportId,
                    values.currentTeamId,
                    values.searchTerm,
                    values.typeFilters,
                    values.trailingEntry
                )

                if (results.length < LOGS_PORTION_LIMIT) {
                    actions.markLogsEnd()
                }
                return [...values.batchExportLogs, ...results]
            },
            revealBackground: () => {
                const newArray = [...values.batchExportLogsBackground, ...values.batchExportLogs]
                actions.clearBatchExportLogsBackground()
                return newArray
            },
        },
        batchExportLogsBackground: {
            __default: [] as BatchExportLogEntry[],
            loadBatchExportLogsBackgroundPoll: async () => {
                if (values.batchExportLogsLoading) {
                    return values.batchExportLogsBackground
                }

                const results = await api.batchExportLogs.search(
                    batchExportId,
                    values.currentTeamId,
                    values.searchTerm,
                    values.typeFilters,
                    null,
                    values.leadingEntry
                )

                return [...results, ...values.batchExportLogsBackground]
            },
        },
    })),
    reducers({
        batchExportLogsTypes: [
            Object.values(BatchExportLogEntryLevel).filter((type) => type !== 'DEBUG'),
            {
                setBatchExportLogsTypes: (_, { typeFilters }) =>
                    typeFilters.map((tf) => tf as BatchExportLogEntryLevel),
            },
        ],
        batchExportLogsBackground: [
            [] as BatchExportLogEntry[],
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
            Object.values(BatchExportLogEntryLevel).filter((type) => type !== 'DEBUG') as CheckboxValueType[],
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
    selectors(({ selectors }) => ({
        leadingEntry: [
            () => [selectors.batchExportLogs, selectors.batchExportLogsBackground],
            (
                batchExportLogs: BatchExportLogEntry[],
                batchExportLogsBackground: BatchExportLogEntry[]
            ): BatchExportLogEntry | null => {
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
            () => [selectors.batchExportLogs, selectors.batchExportLogsBackground],
            (
                batchExportLogs: BatchExportLogEntry[],
                batchExportLogsBackground: BatchExportLogEntry[]
            ): BatchExportLogEntry | null => {
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
