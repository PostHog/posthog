import { ApiConfig } from 'lib/api'

import {
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

export type DataQualitySubjectType = 'table' | 'view'

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

export const checksApi = {
    list: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualityCheckListApi> =>
        isView(ref)
            ? warehouseSavedQueriesChecksList(projectId(), ref.subjectId, { limit })
            : warehouseTablesChecksList(projectId(), ref.subjectId, { limit }),

    create: (ref: DataQualitySubjectRef, body: CreateBody): Promise<DataQualityCheckApi> =>
        isView(ref)
            ? warehouseSavedQueriesChecksCreate(projectId(), ref.subjectId, body)
            : warehouseTablesChecksCreate(projectId(), ref.subjectId, body),

    partialUpdate: (ref: DataQualitySubjectRef, id: string, body: PatchBody): Promise<DataQualityCheckApi> =>
        isView(ref)
            ? warehouseSavedQueriesChecksPartialUpdate(projectId(), ref.subjectId, id, body)
            : warehouseTablesChecksPartialUpdate(projectId(), ref.subjectId, id, body),

    destroy: (ref: DataQualitySubjectRef, id: string): Promise<void> =>
        isView(ref)
            ? warehouseSavedQueriesChecksDestroy(projectId(), ref.subjectId, id)
            : warehouseTablesChecksDestroy(projectId(), ref.subjectId, id),

    run: (ref: DataQualitySubjectRef, id: string): Promise<DataQualitySuiteRunApi> =>
        isView(ref)
            ? warehouseSavedQueriesChecksRunCreate(projectId(), ref.subjectId, id)
            : warehouseTablesChecksRunCreate(projectId(), ref.subjectId, id),

    runAll: (ref: DataQualitySubjectRef): Promise<DataQualitySuiteRunApi> =>
        isView(ref)
            ? warehouseSavedQueriesChecksRunAllCreate(projectId(), ref.subjectId)
            : warehouseTablesChecksRunAllCreate(projectId(), ref.subjectId),

    runs: (ref: DataQualitySubjectRef, id: string): Promise<DataQualityCheckRunApi[]> =>
        isView(ref)
            ? warehouseSavedQueriesChecksRunsList(projectId(), ref.subjectId, id)
            : warehouseTablesChecksRunsList(projectId(), ref.subjectId, id),

    checkTypes: (ref: DataQualitySubjectRef): Promise<DataQualityCheckTypeApi[]> =>
        isView(ref)
            ? warehouseSavedQueriesChecksCheckTypesList(projectId(), ref.subjectId)
            : warehouseTablesChecksCheckTypesList(projectId(), ref.subjectId),

    health: (ref: DataQualitySubjectRef): Promise<DataQualitySubjectHealthApi> =>
        isView(ref)
            ? warehouseSavedQueriesChecksHealthRetrieve(projectId(), ref.subjectId)
            : warehouseTablesChecksHealthRetrieve(projectId(), ref.subjectId),

    suiteRuns: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualitySuiteRunListApi> =>
        isView(ref)
            ? warehouseSavedQueriesCheckSuiteRunsList(projectId(), ref.subjectId, { limit })
            : warehouseTablesCheckSuiteRunsList(projectId(), ref.subjectId, { limit }),

    suiteRunRetrieve: (ref: DataQualitySubjectRef, id: string): Promise<DataQualitySuiteRunApi> =>
        isView(ref)
            ? warehouseSavedQueriesCheckSuiteRunsRetrieve(projectId(), ref.subjectId, id)
            : warehouseTablesCheckSuiteRunsRetrieve(projectId(), ref.subjectId, id),

    suiteRunCheckRuns: (ref: DataQualitySubjectRef, id: string): Promise<DataQualityCheckRunApi[]> =>
        isView(ref)
            ? warehouseSavedQueriesCheckSuiteRunsCheckRunsList(projectId(), ref.subjectId, id)
            : warehouseTablesCheckSuiteRunsCheckRunsList(projectId(), ref.subjectId, id),
}
