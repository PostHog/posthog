import type { TracePageWithBoundsRequestApi } from '../../generated/api.schemas'

export function pageRequest(rows: { id: string; createdAt: string }[]): TracePageWithBoundsRequestApi {
    const createdAts = rows.map((row) => row.createdAt).sort((a, b) => Date.parse(a) - Date.parse(b))
    return {
        trace_ids: rows.map((row) => row.id),
        earliest_created_at: createdAts[0],
        latest_created_at: createdAts[createdAts.length - 1],
    }
}
