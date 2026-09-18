import { CaptureResult } from 'posthog-js'

import { CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT } from './createCustomerJourney'

const JOURNEY_FIELDS = [
    'schema_version',
    'journey_name',
    'attempt_id',
    'region',
    'project_id',
    'organization_id',
    'resource_type',
    'resource_id',
    'trigger',
    'readiness_contract_version',
    'registry_version',
    'readiness_scope',
    'workload_class',
    'visibility_state',
    'outcome',
    'duration_ms',
    'foreground_duration_ms',
    'first_useful_ms',
    'exposures_response_cached',
    'excluded_count',
    'error_type',
    'end_reason',
    'total_count',
    'ready_count',
    'failed_count',
    'pending_count',
    'tile_results_truncated',
] as const

// Token is the installed SDK's unsafe-to-edit field. Keep identity and event association too,
// but never inherit URL context, feature flags, arbitrary superproperties or profile updates.
const SDK_FIELDS = [
    'token',
    'distinct_id',
    '$device_id',
    '$user_id',
    '$session_id',
    '$window_id',
    '$pageview_id',
    '$is_identified',
    '$process_person_profile',
    '$cookieless_mode',
    '$lib',
    '$lib_version',
    '$config_defaults',
    '$lib_rate_limit_remaining_tokens',
    '$event_time_override_provided',
] as const
const INSIGHT_TYPES = ['TRENDS', 'STICKINESS', 'LIFECYCLE', 'FUNNELS', 'RETENTION', 'PATHS'] as const

function record(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        throw new Error('Invalid journey record')
    }
    return value as Record<string, unknown>
}

function projectScalars(source: Record<string, unknown>, fields: readonly string[]): Record<string, unknown> {
    const result: Record<string, unknown> = {}
    for (const field of fields) {
        const value = source[field]
        if (value === undefined) {
            continue
        }
        if (
            typeof value !== 'string' &&
            typeof value !== 'boolean' &&
            !(typeof value === 'number' && Number.isFinite(value))
        ) {
            throw new Error('Invalid journey property')
        }
        Object.defineProperty(result, field, { value, enumerable: true, configurable: true, writable: true })
    }
    return result
}

/** Project after SDK enrichment and caller hooks so only operational data leaves on journey events. */
export function projectCustomerJourneyCapture(event: CaptureResult | null): CaptureResult | null {
    if (!event || !['customer_journey_started', 'customer_journey_finished'].includes(event.event)) {
        return event
    }
    try {
        const source = record(event.properties)
        if (typeof event.uuid !== 'string' || source.schema_version !== 1 || typeof source.attempt_id !== 'string') {
            return null
        }
        const properties = projectScalars(source, [...JOURNEY_FIELDS, ...SDK_FIELDS])
        if (source.$groups !== undefined) {
            const groups = record(source.$groups)
            properties.$groups = projectScalars(groups, Object.keys(groups))
        }
        if (source.$event_time_override_system_time !== undefined) {
            if (!(source.$event_time_override_system_time instanceof Date)) {
                return null
            }
            properties.$event_time_override_system_time = source.$event_time_override_system_time
        }
        if (source.insight_type_summary !== undefined) {
            const summary = record(source.insight_type_summary)
            properties.insight_type_summary = Object.fromEntries(
                INSIGHT_TYPES.filter((type) => summary[type] !== undefined).map((type) => [
                    type,
                    projectScalars(record(summary[type]), [
                        'total_count',
                        'ready_count',
                        'failed_count',
                        'max_duration_ms',
                    ]),
                ])
            )
        }
        if (source.tile_results !== undefined) {
            if (
                !Array.isArray(source.tile_results) ||
                source.tile_results.length > CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT
            ) {
                return null
            }
            properties.tile_results = source.tile_results.map((tile) =>
                projectScalars(record(tile), ['tile_id', 'insight_short_id', 'insight_type', 'state', 'duration_ms'])
            )
        }
        if (event.timestamp !== undefined && !(event.timestamp instanceof Date)) {
            return null
        }
        // Do not spread the envelope: $set/$set_once/$unset can contain initial URLs or profile data.
        return {
            uuid: event.uuid,
            event: event.event,
            properties,
            ...(event.timestamp ? { timestamp: event.timestamp } : {}),
        }
    } catch {
        return null
    }
}
