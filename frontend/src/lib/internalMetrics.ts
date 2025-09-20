import posthog from 'posthog-js'

import api, { getJSONOrNull } from 'lib/api'
import { getResponseBytes } from 'scenes/insights/utils'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'

export interface TimeToSeeDataPayload {
    team_id?: number | null
    type: 'dashboard_load' | 'insight_load' | 'properties_timeline_load' | 'property_values_load' | 'properties_load'
    context: 'dashboard' | 'insight' | 'actors_modal' | 'filters'
    time_to_see_data_ms: number
    primary_interaction_id: string
    query_id?: string
    status?: 'failure' | 'success' | 'cancelled'
    api_response_bytes?: number
    api_url?: string
    insight?: string
    action?: string
    insights_fetched?: number
    insights_fetched_cached?: number
    min_last_refresh?: string | null
    max_last_refresh?: string | null
    // Signifies whether the action was user-initiated or a secondary effect
    is_primary_interaction?: boolean
}

export function currentSessionId(): string | undefined {
    const sessionDetails = posthog.sessionManager?.checkAndGetSessionAndWindowId?.(true)
    return sessionDetails?.sessionId
}

export async function captureTimeToSeeData(teamId: number | null, payload: TimeToSeeDataPayload): Promise<void> {
    if (window.JS_CAPTURE_TIME_TO_SEE_DATA && teamId) {
        if (getCurrentExporterData()) {
            // This is likely we are in a "sharing" context so we are essentially unauthenticated
            return
        }

        try {
            await api.create(`api/projects/${teamId}/insights/timing`, {
                session_id: currentSessionId(),
                current_url: window.location.href,
                ...payload,
            })
        } catch (e) {
            // NOTE: As this is only telemetry, we don't want to block the user if it fails
            console.warn('Failed to capture time to see data', e)
            posthog.captureException(e)
        }
    }
}

/** api.get() wrapped in captureTimeToSeeData() tracking for simple cases of fetching insights or dashboards.
 * This is not in api.ts to avoid circular dependencies, but the principle is the same.
 */
export async function apiGetWithTimeToSeeDataTracking<T>(
    url: string,
    teamId: number | null,
    timeToSeeDataPayload: Omit<
        TimeToSeeDataPayload,
        'api_url' | 'time_to_see_data_ms' | 'status' | 'api_response_bytes'
    >
): Promise<T> {
    let response: Response | undefined
    let responseData: T | undefined
    let error: any
    const requestStartMs = performance.now()
    try {
        response = await api.getResponse(url)
        responseData = await getJSONOrNull(response)
    } catch (e) {
        error = e
    }
    const requestDurationMs = performance.now() - requestStartMs
    void captureTimeToSeeData(teamId, {
        ...timeToSeeDataPayload,
        api_url: url,
        status: error ? 'failure' : 'success',
        api_response_bytes: response && getResponseBytes(response),
        time_to_see_data_ms: requestDurationMs,
    })
    if (!responseData) {
        throw error // If there's no response data, there must have been an error - rethrow it
    }
    return responseData
}
