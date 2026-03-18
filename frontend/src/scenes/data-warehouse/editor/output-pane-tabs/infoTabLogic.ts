import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataModelingJob } from '~/types'

import { sqlEditorLogic } from '../sqlEditorLogic'
import type { infoTabLogicType } from './infoTabLogicType'

const REFRESH_INTERVAL = 10000
const DEFAULT_JOBS_PAGE_SIZE = 10

export interface InfoTableRow {
    name: string
    type: 'source' | 'table'
    view_id?: string
    status?: string
    last_run_at?: string
}

export interface InfoTabLogicProps {
    tabId: string
}

export const infoTabLogic = kea<infoTabLogicType>([
    path(['data-warehouse', 'editor', 'sidebar', 'infoTabLogic']),
    props({} as InfoTabLogicProps),
    key((props) => props.tabId),
    connect((props: InfoTabLogicProps) => ({
        values: [
            sqlEditorLogic({ tabId: props.tabId }),
            ['metadata', 'editingView'],
            databaseTableListLogic,
            ['posthogTablesMap', 'dataWarehouseTablesMap'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueryMap'],
        ],
    })),
    actions({
        setStartingMaterialization: (starting: boolean) => ({ starting }),
    }),
    loaders(({ values }) => ({
        dataModelingJobs: [
            null as PaginatedResponse<DataModelingJob> | null,
            {
                loadDataModelingJobs: async (savedQueryId: string) => {
                    return await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                        savedQueryId,
                        values.dataModelingJobs?.results.length
                            ? Math.max(values.dataModelingJobs.results.length, DEFAULT_JOBS_PAGE_SIZE)
                            : DEFAULT_JOBS_PAGE_SIZE,
                        0
                    )
                },
                loadOlderDataModelingJobs: async () => {
                    const nextUrl = values.dataModelingJobs?.next

                    if (!nextUrl) {
                        return values.dataModelingJobs
                    }

                    const res = await api.get<PaginatedResponse<DataModelingJob>>(nextUrl)
                    res.results = [...(values.dataModelingJobs?.results ?? []), ...res.results]

                    return res
                },
            },
        ],
    })),
    reducers({
        startingMaterialization: [
            false,
            {
                setStartingMaterialization: (_, { starting }: { starting: boolean }) => starting,
                loadDataModelingJobsSuccess: (
                    state: boolean,
                    { dataModelingJobs }: { dataModelingJobs: PaginatedResponse<DataModelingJob> | null }
                ) => {
                    const currentJobStatus = dataModelingJobs?.results?.[0]?.status
                    if (
                        currentJobStatus &&
                        ['Running', 'Completed', 'Failed', 'Cancelled'].includes(currentJobStatus)
                    ) {
                        return false
                    }
                    return state
                },
            },
        ],
    }),
    selectors({
        sourceTableItems: [
            (s) => [s.metadata, s.dataWarehouseSavedQueryMap],
            (metadata, dataWarehouseSavedQueryMap) => {
                if (!metadata) {
                    return []
                }
                return (
                    metadata.table_names?.map((table_name) => {
                        const view = dataWarehouseSavedQueryMap[table_name]
                        if (view) {
                            return {
                                name: table_name,
                                type: 'table',
                                view_id: view.id,
                                status: view.status,
                                last_run_at: view.last_run_at || 'never',
                            }
                        }

                        return {
                            name: table_name,
                            type: 'source',
                            status: undefined,
                            last_run_at: undefined,
                        }
                    }) || []
                )
            },
        ],
        hasMoreJobsToLoad: [(s) => [s.dataModelingJobs], (dataModelingJobs) => !!dataModelingJobs?.next],
    }),
    listeners(({ actions, cache }) => ({
        loadDataModelingJobsSuccess: ({ payload }) => {
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => {
                    if (payload) {
                        actions.loadDataModelingJobs(payload)
                    }
                }, REFRESH_INTERVAL)
                return () => clearTimeout(timeoutId)
            }, 'dataModelingJobsRefreshTimeout')
        },
    })),
    subscriptions(({ actions, values }) => ({
        editingView: (editingView) => {
            if (editingView) {
                if (values.dataModelingJobs === null) {
                    actions.loadDataModelingJobs(editingView.id)
                }
            }
        },
    })),
])
