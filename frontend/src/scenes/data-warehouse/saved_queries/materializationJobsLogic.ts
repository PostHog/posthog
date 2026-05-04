import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'

import { DataModelingJob, DataWarehouseSavedQuery } from '~/types'

import type { materializationJobsLogicType } from './materializationJobsLogicType'

const REFRESH_INTERVAL = 10000
const DEFAULT_JOBS_PAGE_SIZE = 10

export interface MaterializationJobsLogicProps {
    viewId: string
}

export const materializationJobsLogic = kea<materializationJobsLogicType>([
    path(['scenes', 'data-warehouse', 'saved_queries', 'materializationJobsLogic']),
    props({} as MaterializationJobsLogicProps),
    key((props) => props.viewId),
    actions({
        setStartingMaterialization: (starting: boolean) => ({ starting }),
    }),
    loaders(({ values, props }) => ({
        savedQuery: [
            null as DataWarehouseSavedQuery | null,
            {
                loadSavedQuery: async () => {
                    if (!props.viewId) {
                        return null
                    }
                    return await api.dataWarehouseSavedQueries.get(props.viewId)
                },
            },
        ],
        dataModelingJobs: [
            null as PaginatedResponse<DataModelingJob> | null,
            {
                loadDataModelingJobs: async () => {
                    return await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                        props.viewId,
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
        hasMoreJobsToLoad: [(s) => [s.dataModelingJobs], (dataModelingJobs) => !!dataModelingJobs?.next],
    }),
    afterMount(({ actions, props }) => {
        if (props.viewId) {
            actions.loadDataModelingJobs()
            actions.loadSavedQuery()
        }
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.viewId && props.viewId !== oldProps.viewId) {
            actions.loadDataModelingJobs()
            actions.loadSavedQuery()
        }
    }),
    listeners(({ actions, cache }) => ({
        loadDataModelingJobsSuccess: () => {
            // Refresh saved query alongside jobs so latest_error / status / sync_frequency stay in sync.
            actions.loadSavedQuery()
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => {
                    actions.loadDataModelingJobs()
                }, REFRESH_INTERVAL)
                return () => clearTimeout(timeoutId)
            }, 'dataModelingJobsRefreshTimeout')
        },
    })),
])
