import { aiObservabilityTracesPeopleCreate, aiObservabilityTracesPreviewsCreate } from '../generated/api'
import type { TracePersonApi, TracePreviewApi } from '../generated/api.schemas'

/** What a trace asked, what it answered and who it ran for, for example rows. */
export interface TraceSample {
    preview: TracePreviewApi | null
    person: TracePersonApi | null
}

const MAX_TRACES = 100

/** Reads previews and people for the traces. Each read fails on its own, so a failed one only leaves its part out. */
export async function fetchTraceSamples(
    projectId: string,
    traceIds: string[],
    bounds: { earliest: string; latest: string }
): Promise<Record<string, TraceSample>> {
    const ids = [...new Set(traceIds)].slice(0, MAX_TRACES)
    if (ids.length === 0) {
        return {}
    }
    const [previews, people] = await Promise.all([
        aiObservabilityTracesPreviewsCreate(projectId, { trace_ids: ids }).then(
            (response) => response.items,
            () => []
        ),
        aiObservabilityTracesPeopleCreate(projectId, {
            trace_ids: ids,
            earliest_created_at: bounds.earliest,
            latest_created_at: bounds.latest,
        }).then(
            (response) => response.items,
            () => []
        ),
    ])
    const previewById = new Map(previews.map((preview) => [preview.traceId, preview]))
    const personById = new Map(people.map((item) => [item.traceId, item.person]))
    return Object.fromEntries(
        ids.map((id) => [id, { preview: previewById.get(id) ?? null, person: personById.get(id) ?? null }])
    )
}
