import { ApiConfig, ApiError } from 'lib/api'

import {
    dataQualityChecksCheckTypesList,
    dataQualityChecksCreate,
    dataQualityChecksDestroy,
    dataQualityChecksHealthList,
    dataQualityChecksList,
    dataQualityChecksMetricSubjectsList,
    dataQualityChecksOutputSchemaRetrieve,
    dataQualityChecksPartialUpdate,
    dataQualityChecksRunCreate,
    dataQualityChecksRunsList,
    dataQualityChecksSchedulePartialUpdate,
    dataQualityChecksScheduleRetrieve,
    dataQualityChecksSchedulesList,
    dataQualityChecksSubjectsList,
    dataQualityRunsCheckRunsList,
    dataQualityRunsCreate,
    dataQualityRunsList,
    dataQualityRunsRetrieve,
} from './generated/api'
import type {
    DataQualityCheckApi,
    DataQualityCheckRunApi,
    DataQualityCheckScheduleApi,
    DataQualityCheckTypeApi,
    DataQualityMetricSubjectApi,
    DataQualityOutputSchemaApi,
    DataQualitySubjectApi,
    DataQualitySubjectHealthApi,
    DataQualitySubjectScheduleApi,
    DataQualitySuiteRunApi,
    PatchedDataQualityCheckScheduleUpdateApi,
    PaginatedDataQualityOverviewCheckListApi,
    PaginatedDataQualitySuiteRunListApi,
    SubjectTypeEnumApi,
} from './generated/api.schemas'

export function apiErrorDetail(error: unknown): string | null {
    return error instanceof ApiError ? error.detail : null
}

export type DataQualitySubjectType = SubjectTypeEnumApi

export interface DataQualitySubjectRef {
    subjectType: DataQualitySubjectType
    subjectId: string
}

type CreateBody = Omit<Parameters<typeof dataQualityChecksCreate>[1], 'subject_type' | 'subject_uuid'>
type PatchBody = Parameters<typeof dataQualityChecksPartialUpdate>[2]

function projectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

function subjectParams(ref: DataQualitySubjectRef): { subject_type: DataQualitySubjectType; subject_uuid: string } {
    return { subject_type: ref.subjectType, subject_uuid: ref.subjectId }
}

function emptyHealth(ref: DataQualitySubjectRef): DataQualitySubjectHealthApi {
    return { ...subjectParams(ref), health: 'unknown', checks_total: 0, checks_failing: 0 }
}

export const checksApi = {
    metricSubjects: (): Promise<DataQualityMetricSubjectApi[]> => dataQualityChecksMetricSubjectsList(projectId()),

    subjects: (): Promise<DataQualitySubjectApi[]> => dataQualityChecksSubjectsList(projectId()),

    outputSchema: (ref: DataQualitySubjectRef): Promise<DataQualityOutputSchemaApi> => {
        if (ref.subjectType !== 'metric') {
            return Promise.resolve({ columns: [] })
        }
        return dataQualityChecksOutputSchemaRetrieve(projectId(), subjectParams(ref))
    },

    list: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualityOverviewCheckListApi> =>
        dataQualityChecksList(projectId(), { ...subjectParams(ref), limit }),

    create: (ref: DataQualitySubjectRef, body: CreateBody): Promise<DataQualityCheckApi> =>
        dataQualityChecksCreate(projectId(), { ...body, ...subjectParams(ref) }),

    partialUpdate: (id: string, body: PatchBody): Promise<DataQualityCheckApi> =>
        dataQualityChecksPartialUpdate(projectId(), id, body),

    destroy: (id: string): Promise<void> => dataQualityChecksDestroy(projectId(), id),

    run: (id: string): Promise<DataQualitySuiteRunApi> => dataQualityChecksRunCreate(projectId(), id),

    runAll: (ref: DataQualitySubjectRef): Promise<DataQualitySuiteRunApi> =>
        dataQualityRunsCreate(projectId(), subjectParams(ref)),

    runs: (id: string): Promise<DataQualityCheckRunApi[]> => dataQualityChecksRunsList(projectId(), id),

    checkTypes: (ref: DataQualitySubjectRef): Promise<DataQualityCheckTypeApi[]> =>
        dataQualityChecksCheckTypesList(projectId(), { subject_type: ref.subjectType }),

    health: async (ref: DataQualitySubjectRef): Promise<DataQualitySubjectHealthApi> => {
        const rollups = await dataQualityChecksHealthList(projectId(), subjectParams(ref))
        return rollups[0] ?? emptyHealth(ref)
    },

    suiteRuns: (ref: DataQualitySubjectRef, limit: number): Promise<PaginatedDataQualitySuiteRunListApi> =>
        dataQualityRunsList(projectId(), { ...subjectParams(ref), limit }),

    suiteRunRetrieve: (id: string): Promise<DataQualitySuiteRunApi> => dataQualityRunsRetrieve(projectId(), id),

    suiteRunCheckRuns: (id: string): Promise<DataQualityCheckRunApi[]> => dataQualityRunsCheckRunsList(projectId(), id),

    schedule: (ref: DataQualitySubjectRef): Promise<DataQualityCheckScheduleApi> =>
        dataQualityChecksScheduleRetrieve(projectId(), subjectParams(ref)),

    schedules: (): Promise<DataQualitySubjectScheduleApi[]> => dataQualityChecksSchedulesList(projectId()),

    updateSchedule: (
        ref: DataQualitySubjectRef,
        patch: PatchedDataQualityCheckScheduleUpdateApi
    ): Promise<DataQualityCheckScheduleApi> =>
        dataQualityChecksSchedulePartialUpdate(projectId(), { ...patch, ...subjectParams(ref) }),
}
