import { eventToPersonProperties } from '~/common/persons/person-property-utils'
import {
    droppedBloatPropertyCounter,
    featureFlagCalledStripOutcomeCounter,
    strippedFeatureFlagCalledPropertyCounter,
} from '~/ingestion/common/metrics'

// Persistence cache keys that leak from older posthog-js versions into event
// payloads. The SDK stopped sending these in posthog-js#3392; this server-side
// strip covers in-flight and pinned clients. `ph_product_tours` alone embeds
// full tour definitions up to 247 KB per event.
export const BLOAT_PROPERTIES: ReadonlySet<string> = new Set([
    'ph_product_tours',
    '$product_tours_activated',
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

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called' as const

// Prefixes whose keys are always preserved on `$feature_flag_called`. Each names
// an open-ended PostHog property family: `$feature/<flag-key>` (one per evaluated
// flag, server SDKs), `$initial_<prop>` (first-touch super-properties), and
// `$session_entry_<prop>` (session entry-point context).
export const FEATURE_FLAG_CALLED_KEEP_PREFIXES: readonly string[] = ['$feature/', '$initial_', '$session_entry_']

// Allowed property keys on `$feature_flag_called` events. The event is
// SDK-emitted with a fixed schema, but SDKs' cross-cutting methods (`register`,
// super-properties) leak unrelated keys onto it. PostHog owns this event's
// schema, so we strip non-whitelisted keys before ClickHouse persistence.
// Compiled from auditing all PostHog SDKs, a `system.query_log` audit of
// actively-used insights/cohorts referencing `$feature_flag_called`, and the CDP
// legacy-plugin destination/transformation property mappings.
export const FEATURE_FLAG_CALLED_KEEP: ReadonlySet<string> = new Set<string>([
    // Flag-specific (SDK audit)
    '$feature_flag',
    '$feature_flag_response',
    '$feature_flag_id',
    '$feature_flag_version',
    '$feature_flag_reason',
    '$feature_flag_request_id',
    '$feature_flag_evaluated_at',
    '$feature_flag_error',
    '$feature_flag_payload',
    '$feature_flag_definitions_loaded_at',
    'locally_evaluated',
    '$feature_flag_bootstrapped_response',
    '$feature_flag_bootstrapped_payload',
    '$used_bootstrap_value',
    '$feature_flag_original_response',
    '$feature_flag_original_payload',

    // SDK identification
    '$lib',
    '$lib_version',

    // Active feature flags — CDP destinations (e.g. rudderstack-posthog,
    // posthog-laudspeaker) map this onto `context.active_feature_flags`, so it must
    // survive on `$feature_flag_called` events forwarded to those destinations.
    '$active_feature_flags',

    // Person/group writes consumed downstream — `$set` is mirrored into the
    // event row's `person_properties` column by createEvent; `$groups` is
    // consumed by processGroupsStep (the step immediately after prepareEvent)
    // to populate the `$group_0..$group_4` columns. `$set_once`/`$unset`
    // travel with `$set` for symmetry, and `$insert_id`/`$sent_at` are
    // consumed by downstream destinations.
    '$set',
    '$set_once',
    '$unset',
    '$groups',
    '$insert_id',
    '$sent_at',

    // Device / session identity
    '$device_id',
    '$session_id',
    '$window_id',
    '$is_identified',

    // URL / page / screen context
    '$current_url',
    '$pathname',
    '$host',
    '$screen_name',

    // Platform / device
    '$device_type',
    '$os',
    '$browser',
    '$app_version',

    // GeoIP family
    '$ip',
    '$geoip_country_code',
    '$geoip_country_name',
    '$geoip_city_name',
    '$geoip_continent_code',
    '$geoip_continent_name',
    '$geoip_latitude',
    '$geoip_longitude',
    '$geoip_postal_code',
    '$geoip_time_zone',
    '$geoip_subdivision_1_code',
    '$geoip_subdivision_1_name',
    '$geoip_subdivision_2_code',
    '$geoip_subdivision_2_name',

    // Groups
    '$group_0',
    '$group_1',
    '$group_2',
    '$group_3',
    '$group_4',

    // Standard PostHog auto-captured / super-properties (campaign + UTM, web and
    // mobile device, OS, referrer, screen/viewport, raw user agent). Reused from
    // the canonical person-property mapping list so the two stay in sync. Their
    // `$initial_*` first-touch variants are kept via FEATURE_FLAG_CALLED_KEEP_PREFIXES.
    ...eventToPersonProperties,

    // Standard properties not in the person-mapping list above.
    '$user_id',
    '$anon_distinct_id',
    '$device',
    '$device_name',
    '$device_model',
    '$device_manufacturer',
    '$channel_type',
    '$event_type',
    '$session_duration',
    '$start_timestamp',
    '$entry_current_url',
    '$pageview_id',
])

// A variant-string `$feature_flag_response` marks a multivariate flag evaluation —
// a possible experiment exposure whose breakdown/exposure properties must survive.
// Every other response type (boolean, null, number, object, or absent) is stripped.
function isMultivariateFlagResponse(properties: Record<string, any>): boolean {
    return typeof properties['$feature_flag_response'] === 'string'
}

// Strips non-whitelisted keys and returns the property count seen before stripping.
export function stripFeatureFlagCalledProperties(properties: Record<string, any>): number {
    if (isMultivariateFlagResponse(properties)) {
        featureFlagCalledStripOutcomeCounter.labels('kept_multivariate').inc()
        return Object.keys(properties).length
    }

    const keys = Object.keys(properties)
    let stripped = 0
    for (const key of keys) {
        if (FEATURE_FLAG_CALLED_KEEP.has(key)) {
            continue
        }
        if (FEATURE_FLAG_CALLED_KEEP_PREFIXES.some((prefix) => key.startsWith(prefix))) {
            continue
        }
        delete properties[key]
        stripped++
    }
    if (stripped > 0) {
        strippedFeatureFlagCalledPropertyCounter.inc(stripped)
    }
    featureFlagCalledStripOutcomeCounter.labels('stripped').inc()
    return keys.length
}
