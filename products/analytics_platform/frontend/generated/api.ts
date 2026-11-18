import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    PrecomputeDebugResponseApi,
    PrecomputeDebugStateParams,
    PrecomputeInvalidateRequestApi,
    PrecomputeInvalidateResponseApi,
} from './api.schemas'

export const getPrecomputeDebugInvalidateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/precompute_debug/invalidate/`
}

/**
 * Marks the team's READY precompute jobs stale so the next read recomputes them, e.g. after a source resync changed the underlying data. Optionally scoped to a single query hash. PENDING jobs are left alone: anything in flight is already computing against current data.
 * @summary Invalidate stored precompute for this team (staff only)
 */
export const precomputeDebugInvalidate = async (
    projectId: string,
    precomputeInvalidateRequestApi?: PrecomputeInvalidateRequestApi,
    options?: RequestInit
): Promise<PrecomputeInvalidateResponseApi> => {
    return apiMutator<PrecomputeInvalidateResponseApi>(getPrecomputeDebugInvalidateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(precomputeInvalidateRequestApi),
    })
}

export const getPrecomputeDebugStateUrl = (projectId: string, params?: PrecomputeDebugStateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/precompute_debug/state/?${stringifiedParams}`
        : `/api/projects/${projectId}/precompute_debug/state/`
}

/**
 * Staff/dev-only debug view of the team's lazy precompute store: which query hashes are stored, which buckets each covers, per-bucket TTL, and — where recoverable from query_log — the originating query (with filters) each hash serves.
 * @summary Inspect stored lazy-precompute state (staff only)
 */
export const precomputeDebugState = async (
    projectId: string,
    params?: PrecomputeDebugStateParams,
    options?: RequestInit
): Promise<PrecomputeDebugResponseApi> => {
    return apiMutator<PrecomputeDebugResponseApi>(getPrecomputeDebugStateUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
