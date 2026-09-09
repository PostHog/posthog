import { ApiConfig, ApiError } from 'lib/api'

import {
    dataCatalogMetricsCheckSuiteRunsCheckRunsList,
    dataCatalogMetricsCheckSuiteRunsList,
    dataCatalogMetricsCheckSuiteRunsRetrieve,
    dataCatalogMetricsChecksCheckTypesList,
    dataCatalogMetricsChecksCreate,
    dataCatalogMetricsChecksDestroy,
    dataCatalogMetricsChecksHealthRetrieve,
    dataCatalogMetricsChecksList,
    dataCatalogMetricsChecksPartialUpdate,
    dataCatalogMetricsChecksRunAllCreate,
    dataCatalogMetricsChecksRunCreate,
    dataCatalogMetricsChecksRunsList,
    warehouseSavedQueriesCheckSuiteRunsCheckRunsList,
    warehouseSavedQueriesCheckSuiteRunsList,
    warehouseSavedQueriesCheckSuiteRunsRetrieve,
    warehouseSavedQueriesChecksCheckTypesList,
    warehouseSavedQueriesChecksCreate,
    warehouseSavedQueriesChecksDestroy,
    warehouseSavedQueriesChecksHealthRetrieve,
    warehouseSavedQueriesChecksList,
    warehouseSavedQueriesChecksPartialUpdate,
    warehouseSavedQueriesChecksRunAllCreate,
    warehouseSavedQueriesChecksRunCreate,
    warehouseSavedQueriesChecksRunsList,
    warehouseTablesCheckSuiteRunsCheckRunsList,
    warehouseTablesCheckSuiteRunsList,
    warehouseTablesCheckSuiteRunsRetrieve,
    warehouseTablesChecksCheckTypesList,
    warehouseTablesChecksCreate,
    warehouseTablesChecksDestroy,
    warehouseTablesChecksHealthRetrieve,
    warehouseTablesChecksList,
    warehouseTablesChecksPartialUpdate,
    warehouseTablesChecksRunAllCreate,
    warehouseTablesChecksRunCreate,
    warehouseTablesChecksRunsList,
} from './generated/api'
import type {
    DataQualityCheckApi,
    DataQualityCheckRunApi,
    DataQualityCheckTypeApi,
    DataQualitySubjectHealthApi,
    DataQualitySuiteRunApi,
    PaginatedDataQualityCheckListApi,
    PaginatedDataQualitySuiteRunListApi,
} from './generated/api.schemas'

export function apiErrorDetail(error: unknown): string | null {
    return error instanceof ApiError ? error.detail : null
}

export type DataQualitySubjectType = 'table' | 'view' | 'metric'

export interface DataQualitySubjectRef {
    subjectType: DataQualitySubjectType
    subjectId: string
}

type CreateBody = Parameters<typeof warehouseSavedQueriesChecksCreate>[2]
type PatchBody = Parameters<typeof warehouseSavedQueriesChecksPartialUpdate>[3]

function projectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

function isView({ subjectType }: DataQualitySubjectRef): boolean {
    return subjectType === 'view'
}

function isMetric({ subjectType }: DataQualitySubjectRef): boolean {
    return subjectType === 'metric'
}

export const checksApi = {
    list: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualityCheckListApi> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksList(projectId(), ref.subjectId, { limit })
            : isView(ref)
              ? warehouseSavedQueriesChecksList(projectId(), ref.subjectId, { limit })
              : warehouseTablesChecksList(projectId(), ref.subjectId, { limit }),

    create: (ref: DataQualitySubjectRef, body: CreateBody): Promise<DataQualityCheckApi> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksCreate(projectId(), ref.subjectId, body)
            : isView(ref)
              ? warehouseSavedQueriesChecksCreate(projectId(), ref.subjectId, body)
              : warehouseTablesChecksCreate(projectId(), ref.subjectId, body),

    partialUpdate: (ref: DataQualitySubjectRef, id: string, body: PatchBody): Promise<DataQualityCheckApi> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksPartialUpdate(projectId(), ref.subjectId, id, body)
            : isView(ref)
              ? warehouseSavedQueriesChecksPartialUpdate(projectId(), ref.subjectId, id, body)
              : warehouseTablesChecksPartialUpdate(projectId(), ref.subjectId, id, body),

    destroy: (ref: DataQualitySubjectRef, id: string): Promise<void> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksDestroy(projectId(), ref.subjectId, id)
            : isView(ref)
              ? warehouseSavedQueriesChecksDestroy(projectId(), ref.subjectId, id)
              : warehouseTablesChecksDestroy(projectId(), ref.subjectId, id),

    run: (ref: DataQualitySubjectRef, id: string): Promise<DataQualitySuiteRunApi> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksRunCreate(projectId(), ref.subjectId, id)
            : isView(ref)
              ? warehouseSavedQueriesChecksRunCreate(projectId(), ref.subjectId, id)
              : warehouseTablesChecksRunCreate(projectId(), ref.subjectId, id),

    runAll: (ref: DataQualitySubjectRef): Promise<DataQualitySuiteRunApi> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksRunAllCreate(projectId(), ref.subjectId)
            : isView(ref)
              ? warehouseSavedQueriesChecksRunAllCreate(projectId(), ref.subjectId)
              : warehouseTablesChecksRunAllCreate(projectId(), ref.subjectId),

    runs: (ref: DataQualitySubjectRef, id: string): Promise<DataQualityCheckRunApi[]> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksRunsList(projectId(), ref.subjectId, id)
            : isView(ref)
              ? warehouseSavedQueriesChecksRunsList(projectId(), ref.subjectId, id)
              : warehouseTablesChecksRunsList(projectId(), ref.subjectId, id),

    checkTypes: (ref: DataQualitySubjectRef): Promise<DataQualityCheckTypeApi[]> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksCheckTypesList(projectId(), ref.subjectId)
            : isView(ref)
              ? warehouseSavedQueriesChecksCheckTypesList(projectId(), ref.subjectId)
              : warehouseTablesChecksCheckTypesList(projectId(), ref.subjectId),

    health: (ref: DataQualitySubjectRef): Promise<DataQualitySubjectHealthApi> =>
        isMetric(ref)
            ? dataCatalogMetricsChecksHealthRetrieve(projectId(), ref.subjectId)
            : isView(ref)
              ? warehouseSavedQueriesChecksHealthRetrieve(projectId(), ref.subjectId)
              : warehouseTablesChecksHealthRetrieve(projectId(), ref.subjectId),

    suiteRuns: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualitySuiteRunListApi> =>
        isMetric(ref)
            ? dataCatalogMetricsCheckSuiteRunsList(projectId(), ref.subjectId, { limit })
            : isView(ref)
              ? warehouseSavedQueriesCheckSuiteRunsList(projectId(), ref.subjectId, { limit })
              : warehouseTablesCheckSuiteRunsList(projectId(), ref.subjectId, { limit }),

    suiteRunRetrieve: (ref: DataQualitySubjectRef, id: string): Promise<DataQualitySuiteRunApi> =>
        isMetric(ref)
            ? dataCatalogMetricsCheckSuiteRunsRetrieve(projectId(), ref.subjectId, id)
            : isView(ref)
              ? warehouseSavedQueriesCheckSuiteRunsRetrieve(projectId(), ref.subjectId, id)
              : warehouseTablesCheckSuiteRunsRetrieve(projectId(), ref.subjectId, id),

    suiteRunCheckRuns: (ref: DataQualitySubjectRef, id: string): Promise<DataQualityCheckRunApi[]> =>
        isMetric(ref)
            ? dataCatalogMetricsCheckSuiteRunsCheckRunsList(projectId(), ref.subjectId, id)
            : isView(ref)
              ? warehouseSavedQueriesCheckSuiteRunsCheckRunsList(projectId(), ref.subjectId, id)
              : warehouseTablesCheckSuiteRunsCheckRunsList(projectId(), ref.subjectId, id),
}
