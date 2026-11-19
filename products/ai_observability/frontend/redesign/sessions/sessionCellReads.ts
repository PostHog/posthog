import { aiObservabilityTracesPeopleCreate, aiObservabilityTracesPreviewsCreate } from '../../generated/api'
import type { SessionListItemApi, TracePeopleListApi, TracePreviewListApi } from '../../generated/api.schemas'

export function readSessionTitles(projectId: string, sessions: SessionListItemApi[]): Promise<TracePreviewListApi> {
    return aiObservabilityTracesPreviewsCreate(projectId, { trace_ids: sessions.map((row) => row.firstTraceId) })
}

export function readSessionPeople(projectId: string, sessions: SessionListItemApi[]): Promise<TracePeopleListApi> {
    const createdAts = sessions.map((row) => row.firstTraceCreatedAt).sort((a, b) => Date.parse(a) - Date.parse(b))
    return aiObservabilityTracesPeopleCreate(projectId, {
        trace_ids: sessions.map((row) => row.firstTraceId),
        earliest_created_at: createdAts[0],
        latest_created_at: createdAts[createdAts.length - 1],
    })
}
