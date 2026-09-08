import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DataWarehouseSavedQuery } from '~/types'

import { dataModelingJobsList } from 'products/data_warehouse/frontend/generated/api'
import {
    type DataModelingJobApi,
    DataModelingJobStatusEnumApi,
    type PaginatedDataModelingJobListApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { modelsSceneLogic } from './modelsSceneLogic'

export const RUNS_PAGE_SIZE = 20

export const RUN_STATUSES: DataModelingJobStatusEnumApi[] = Object.values(DataModelingJobStatusEnumApi)

function isRunStatus(status: unknown): status is DataModelingJobStatusEnumApi {
    return typeof status === 'string' && (RUN_STATUSES as string[]).includes(status)
}

export interface ModelRun {
    job: DataModelingJobApi
    /** Null when the model has since been deleted */
    modelName: string | null
    /** Null when the model has no node yet, or has been deleted */
    nodeId: string | null
}

export interface modelsRunsLogicValues {
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[] // dataWarehouseViewsLogic
    savedQueryIdToNodeId: Record<string, string> // modelsSceneLogic
    statusFilter: DataModelingJobStatusEnumApi | null
    page: number
    jobs: PaginatedDataModelingJobListApi | null
    jobsLoading: boolean
    runs: ModelRun[]
}

export interface modelsRunsLogicActions {
    setStatusFilter: (statusFilter: DataModelingJobStatusEnumApi | null) => {
        statusFilter: DataModelingJobStatusEnumApi | null
    }
    setPage: (page: number) => { page: number }
    loadJobs: () => any
    loadJobsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadJobsSuccess: (
        jobs: PaginatedDataModelingJobListApi | null,
        payload?: any
    ) => {
        jobs: PaginatedDataModelingJobListApi | null
        payload?: any
    }
}

export interface modelsRunsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        runs: (
            jobs: PaginatedDataModelingJobListApi | null,
            dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
            savedQueryIdToNodeId: Record<string, string>
        ) => ModelRun[]
    }
}

export type modelsRunsLogicType = MakeLogicType<
    modelsRunsLogicValues,
    modelsRunsLogicActions,
    Record<string, any>,
    modelsRunsLogicMeta
>

export const modelsRunsLogic = kea<modelsRunsLogicType>([
    path(['scenes', 'models', 'modelsRunsLogic']),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries'], modelsSceneLogic, ['savedQueryIdToNodeId']],
    })),
    actions({
        setStatusFilter: (statusFilter: DataModelingJobStatusEnumApi | null) => ({ statusFilter }),
        setPage: (page: number) => ({ page }),
    }),
    reducers({
        statusFilter: [
            null as DataModelingJobStatusEnumApi | null,
            {
                setStatusFilter: (_, { statusFilter }) => statusFilter,
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setStatusFilter: () => 1,
            },
        ],
    }),
    loaders(({ values }) => ({
        jobs: {
            __default: null as PaginatedDataModelingJobListApi | null,
            loadJobs: async (_, breakpoint) => {
                const response = await dataModelingJobsList(String(teamLogic.values.currentTeamId), {
                    limit: RUNS_PAGE_SIZE,
                    offset: (values.page - 1) * RUNS_PAGE_SIZE,
                    status: values.statusFilter ?? undefined,
                })
                breakpoint()
                return response
            },
        },
    })),
    selectors({
        runs: [
            (s) => [s.jobs, s.dataWarehouseSavedQueries, s.savedQueryIdToNodeId],
            (
                jobs: PaginatedDataModelingJobListApi | null,
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                savedQueryIdToNodeId: Record<string, string>
            ): ModelRun[] => {
                const nameById = new Map(dataWarehouseSavedQueries.map((view) => [view.id, view.name]))
                return (jobs?.results ?? []).map((job) => ({
                    job,
                    modelName: job.saved_query_id ? (nameById.get(job.saved_query_id) ?? null) : null,
                    nodeId: job.saved_query_id ? (savedQueryIdToNodeId[job.saved_query_id] ?? null) : null,
                }))
            },
        ],
    }),
    listeners(({ actions }) => ({
        setStatusFilter: () => actions.loadJobs(),
        setPage: () => actions.loadJobs(),
    })),
    urlToAction(({ actions, values }) => ({
        [urls.models()]: (_, searchParams) => {
            if (searchParams.tab !== 'runs') {
                return
            }
            const statusFilter = isRunStatus(searchParams.status) ? searchParams.status : null
            if (statusFilter !== values.statusFilter) {
                actions.setStatusFilter(statusFilter)
            }
        },
    })),
    actionToUrl(() => ({
        setStatusFilter: ({ statusFilter }) => {
            const searchParams = { ...router.values.searchParams }
            if (statusFilter) {
                searchParams.status = statusFilter
            } else {
                delete searchParams.status
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams]
        },
    })),
    afterMount(({ actions, values }) => {
        // urlToAction already loads when the URL carries a status filter
        if (!values.jobsLoading) {
            actions.loadJobs()
        }
    }),
])
