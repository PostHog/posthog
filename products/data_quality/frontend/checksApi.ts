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
type PageParams = Parameters<typeof warehouseSavedQueriesChecksList>[2]

interface SubjectRoutes {
    list: (projectId: string, subjectId: string, params?: PageParams) => Promise<PaginatedDataQualityCheckListApi>
    create: (projectId: string, subjectId: string, body: CreateBody) => Promise<DataQualityCheckApi>
    partialUpdate: (projectId: string, subjectId: string, id: string, body?: PatchBody) => Promise<DataQualityCheckApi>
    destroy: (projectId: string, subjectId: string, id: string) => Promise<void>
    run: (projectId: string, subjectId: string, id: string) => Promise<DataQualitySuiteRunApi>
    runAll: (projectId: string, subjectId: string) => Promise<DataQualitySuiteRunApi>
    runs: (projectId: string, subjectId: string, id: string) => Promise<DataQualityCheckRunApi[]>
    checkTypes: (projectId: string, subjectId: string) => Promise<DataQualityCheckTypeApi[]>
    health: (projectId: string, subjectId: string) => Promise<DataQualitySubjectHealthApi>
    suiteRuns: (
        projectId: string,
        subjectId: string,
        params?: PageParams
    ) => Promise<PaginatedDataQualitySuiteRunListApi>
    suiteRunRetrieve: (projectId: string, subjectId: string, id: string) => Promise<DataQualitySuiteRunApi>
    suiteRunCheckRuns: (projectId: string, subjectId: string, id: string) => Promise<DataQualityCheckRunApi[]>
}

const ROUTES: Record<DataQualitySubjectType, SubjectRoutes> = {
    table: {
        list: warehouseTablesChecksList,
        create: warehouseTablesChecksCreate,
        partialUpdate: warehouseTablesChecksPartialUpdate,
        destroy: warehouseTablesChecksDestroy,
        run: warehouseTablesChecksRunCreate,
        runAll: warehouseTablesChecksRunAllCreate,
        runs: warehouseTablesChecksRunsList,
        checkTypes: warehouseTablesChecksCheckTypesList,
        health: warehouseTablesChecksHealthRetrieve,
        suiteRuns: warehouseTablesCheckSuiteRunsList,
        suiteRunRetrieve: warehouseTablesCheckSuiteRunsRetrieve,
        suiteRunCheckRuns: warehouseTablesCheckSuiteRunsCheckRunsList,
    },
    view: {
        list: warehouseSavedQueriesChecksList,
        create: warehouseSavedQueriesChecksCreate,
        partialUpdate: warehouseSavedQueriesChecksPartialUpdate,
        destroy: warehouseSavedQueriesChecksDestroy,
        run: warehouseSavedQueriesChecksRunCreate,
        runAll: warehouseSavedQueriesChecksRunAllCreate,
        runs: warehouseSavedQueriesChecksRunsList,
        checkTypes: warehouseSavedQueriesChecksCheckTypesList,
        health: warehouseSavedQueriesChecksHealthRetrieve,
        suiteRuns: warehouseSavedQueriesCheckSuiteRunsList,
        suiteRunRetrieve: warehouseSavedQueriesCheckSuiteRunsRetrieve,
        suiteRunCheckRuns: warehouseSavedQueriesCheckSuiteRunsCheckRunsList,
    },
    metric: {
        list: dataCatalogMetricsChecksList,
        create: dataCatalogMetricsChecksCreate,
        partialUpdate: dataCatalogMetricsChecksPartialUpdate,
        destroy: dataCatalogMetricsChecksDestroy,
        run: dataCatalogMetricsChecksRunCreate,
        runAll: dataCatalogMetricsChecksRunAllCreate,
        runs: dataCatalogMetricsChecksRunsList,
        checkTypes: dataCatalogMetricsChecksCheckTypesList,
        health: dataCatalogMetricsChecksHealthRetrieve,
        suiteRuns: dataCatalogMetricsCheckSuiteRunsList,
        suiteRunRetrieve: dataCatalogMetricsCheckSuiteRunsRetrieve,
        suiteRunCheckRuns: dataCatalogMetricsCheckSuiteRunsCheckRunsList,
    },
}

function projectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

function routesFor({ subjectType }: DataQualitySubjectRef): SubjectRoutes {
    return ROUTES[subjectType]
}

export const checksApi = {
    list: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualityCheckListApi> =>
        routesFor(ref).list(projectId(), ref.subjectId, { limit }),

    create: (ref: DataQualitySubjectRef, body: CreateBody): Promise<DataQualityCheckApi> =>
        routesFor(ref).create(projectId(), ref.subjectId, body),

    partialUpdate: (ref: DataQualitySubjectRef, id: string, body: PatchBody): Promise<DataQualityCheckApi> =>
        routesFor(ref).partialUpdate(projectId(), ref.subjectId, id, body),

    destroy: (ref: DataQualitySubjectRef, id: string): Promise<void> =>
        routesFor(ref).destroy(projectId(), ref.subjectId, id),

    run: (ref: DataQualitySubjectRef, id: string): Promise<DataQualitySuiteRunApi> =>
        routesFor(ref).run(projectId(), ref.subjectId, id),

    runAll: (ref: DataQualitySubjectRef): Promise<DataQualitySuiteRunApi> =>
        routesFor(ref).runAll(projectId(), ref.subjectId),

    runs: (ref: DataQualitySubjectRef, id: string): Promise<DataQualityCheckRunApi[]> =>
        routesFor(ref).runs(projectId(), ref.subjectId, id),

    checkTypes: (ref: DataQualitySubjectRef): Promise<DataQualityCheckTypeApi[]> =>
        routesFor(ref).checkTypes(projectId(), ref.subjectId),

    health: (ref: DataQualitySubjectRef): Promise<DataQualitySubjectHealthApi> =>
        routesFor(ref).health(projectId(), ref.subjectId),

    suiteRuns: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualitySuiteRunListApi> =>
        routesFor(ref).suiteRuns(projectId(), ref.subjectId, { limit }),

    suiteRunRetrieve: (ref: DataQualitySubjectRef, id: string): Promise<DataQualitySuiteRunApi> =>
        routesFor(ref).suiteRunRetrieve(projectId(), ref.subjectId, id),

    suiteRunCheckRuns: (ref: DataQualitySubjectRef, id: string): Promise<DataQualityCheckRunApi[]> =>
        routesFor(ref).suiteRunCheckRuns(projectId(), ref.subjectId, id),
}
