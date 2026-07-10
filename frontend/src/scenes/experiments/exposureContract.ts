import {
    ExperimentEventExposureConfig,
    ExperimentExposureConfig,
    ExperimentExposureCriteria,
    NodeKind,
} from '~/queries/schema/schema-general'

/**
 * The flag exposure event contract for experiments. Mirrors the backend chokepoint
 * `get_exposure_event_and_property` in
 * products/experiments/backend/hogql_queries/exposure_query_logic.py so the event and
 * variant-property decision lives in a single place on the frontend too.
 */
export const EXPOSURE_DEFAULT_EVENT = '$feature_flag_called'
export const EXPOSURE_FEATURE_FLAG_RESPONSE_PROPERTY = '$feature_flag_response'
export const EXPOSURE_FEATURE_FLAG_PROPERTY = '$feature_flag'

/** The `$feature/<flag_key>` event property that carries the variant for custom exposure events. */
export function featureFlagVariantProperty(featureFlagKey: string): string {
    return `$feature/${featureFlagKey}`
}

function isEventConfig(config: ExperimentExposureConfig): config is ExperimentEventExposureConfig {
    return config.kind === NodeKind.ExperimentEventExposureConfig || 'event' in config
}

/**
 * Determines which event and variant property carry the exposure for an experiment.
 *
 * - No exposure config, or a `$feature_flag_called` config: the default event, with the variant on
 *   `$feature_flag_response`.
 * - Any custom exposure event or action: that event (default event name for actions, which match
 *   multiple events), with the variant on `$feature/<flag_key>`.
 */
export function getExposureEventAndProperty({
    featureFlagKey,
    exposureCriteria,
}: {
    featureFlagKey: string
    exposureCriteria: ExperimentExposureCriteria | undefined
}): { event: string; variantProperty: string } {
    const exposureConfig = exposureCriteria?.exposure_config

    if (exposureConfig && !(isEventConfig(exposureConfig) && exposureConfig.event === EXPOSURE_DEFAULT_EVENT)) {
        return {
            event: isEventConfig(exposureConfig) ? exposureConfig.event : EXPOSURE_DEFAULT_EVENT,
            variantProperty: featureFlagVariantProperty(featureFlagKey),
        }
    }

    return { event: EXPOSURE_DEFAULT_EVENT, variantProperty: EXPOSURE_FEATURE_FLAG_RESPONSE_PROPERTY }
}
