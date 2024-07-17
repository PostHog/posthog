import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { LOGS_PORTION_LIMIT } from 'lib/constants'

import { ExternalDataJob, ExternalDataSourceSchema, LogEntry, LogEntryLevel } from '~/types'

import type { schemaLogLogicType } from './schemaLogLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']

export interface SchemaLogLogicProps {
    job: ExternalDataJob
}

export const schemaLogLogic = kea<schemaLogLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'source', 'schemaLogLogic']),
    props({} as SchemaLogLogicProps),
    key(({ job }) => job.id),
    actions({
        clearBackgroundLogs: true,
        setLogLevelFilters: (levelFilters: LogEntryLevel[]) => ({ levelFilters }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSchema: (schemaId: ExternalDataSourceSchema['id']) => ({ schemaId }),
        markLogsEnd: true,
    }),
    loaders(({ values, actions, cache, props }) => ({
        logs: {
            __default: [] as LogEntry[],
            loadSchemaLogs: async () => {
                const response = await api.externalDataSchemas.logs(props.job.schema.id, {
                    level: values.levelFilters.join(','),
                    search: values.searchTerm,
                    instance_id: props.job.workflow_run_id,
                })

                if (!cache.pollingInterval) {
                    cache.pollingInterval = setInterval(actions.loadSchemaLogsBackgroundPoll, 2000)
                }

                return response.results
            },
            loadSchemaLogsMore: async () => {
                if (!values.selectedSchemaId) {
                    return []
                }
                const response = await api.externalDataSchemas.logs(values.selectedSchemaId, {
                    level: values.levelFilters.join(','),
                    search: values.searchTerm,
                    instance_id: props.job.workflow_run_id,
                    before: values.leadingEntry?.timestamp,
                })

                if (response.results.length < LOGS_PORTION_LIMIT) {
                    actions.markLogsEnd()
                }

                return [...values.logs, ...response.results]
            },
            revealBackground: () => {
                const newArray = [...values.logsBackground, ...values.logs]
                actions.clearBackgroundLogs()
                return newArray
            },
        },
        logsBackground: {
            __default: [] as LogEntry[],
            loadSchemaLogsBackgroundPoll: async () => {
                const response = await api.externalDataSchemas.logs(props.job.schema.id, {
                    level: values.levelFilters.join(','),
                    search: values.searchTerm,
                    instance_id: props.job.workflow_run_id,
                    after: values.leadingEntry?.timestamp,
                })

                return [...response.results, ...values.logsBackground]
            },
        },
    })),
    reducers({
        levelFilters: [
            DEFAULT_LOG_LEVELS,
            {
                setLogLevelFilters: (_, { levelFilters }) => levelFilters,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        selectedSchemaId: [
            null as string | null,
            {
                setSchema: (_, { schemaId }) => schemaId,
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                loadSchemaLogsSuccess: (_, { logs }) => logs.length >= LOGS_PORTION_LIMIT,
                markLogsEnd: () => false,
            },
        ],
    }),
    selectors({
        leadingEntry: [
            (s) => [s.logs, s.logsBackground],
            (logs, logsBackground): LogEntry | null => {
                if (logsBackground.length) {
                    return logsBackground[0]
                }
                if (logs.length) {
                    return logs[0]
                }
                return null
            },
        ],
    }),
    listeners(({ actions }) => ({
        setLogLevelFilters: () => {
            actions.loadSchemaLogs()
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm) {
                await breakpoint(1000)
            }
            actions.loadSchemaLogs()
        },
        setSchema: () => {
            actions.loadSchemaLogs()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadSchemaLogs()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])
