import { droppedBloatPropertyCounter } from '../../worker/ingestion/event-pipeline/metrics'

// Persistence cache keys that leak from older posthog-js versions into event
// payloads. The SDK stopped sending these in posthog-js#3392; this server-side
// strip covers in-flight and pinned clients. `ph_product_tours` alone embeds
// full tour definitions up to 247 KB per event.
export const BLOAT_PROPERTIES: ReadonlySet<string> = new Set([
    'ph_product_tours',
    '$session_recording_remote_config',
    '$product_tours_activated',
    '$product_tours_enabled_server_side',
    '$surveys_activated',
    '$feature_flag_payloads',
    '$override_feature_flag_payloads',
])

export function stripBloatProperties(properties: Record<string, any>): void {
    for (const key of BLOAT_PROPERTIES) {
        if (key in properties) {
            delete properties[key]
            droppedBloatPropertyCounter.labels(key).inc()
        }
    }
}
