import {
    ExperimentEventExposureConfig,
    ExperimentExposureConfig,
    ExperimentExposureCriteria,
    HogQLQueryModifiers,
    NodeKind,
} from '~/queries/schema/schema-general'
import { Experiment, PropertyFilterType, PropertyOperator } from '~/types'

/**
 * The flag exposure event contract for experiments. Mirrors the backend chokepoint
 * `get_exposure_event_and_property` in
 * products/experiments/backend/hogql_queries/exposure_query_logic.py so the event and
 * variant-property decision lives in a single place on the frontend too.
 */

/**
 * The stored sentinel meaning "default exposure", not necessarily the event that gets queried.
 * An exposure config naming it is the default exposure rather than a custom one, so the backend
 * resolves it the same way as an absent config (`get_exposure_config_params_for_builder`).
 *
 * Use this only to recognize the default; for the event actually counted, use the experiment's
 * server-resolved event (`experimentLogic`'s `resolvedExposureEvent`), which accounts for the
 * `$experiment_exposure` rollout.
 */
export const EXPOSURE_DEFAULT_EVENT = '$feature_flag_called'
export const EXPERIMENT_EXPOSURE_EVENT = '$experiment_exposure'
export const EXPOSURE_FEATURE_FLAG_RESPONSE_PROPERTY = '$feature_flag_response'

/**
 * The event an experiment's default exposure is actually counted on, as resolved by the backend
 * (`resolve_default_exposure_event`). Falls back to the pre-rollout default for an experiment that
 * hasn't come from the API yet — a locally-constructed draft, or an older cached payload.
 */
export function resolvedExposureEvent(
    experiment: Pick<Experiment, 'resolved_exposure_event'>,
    fallbackEvent: string = EXPOSURE_DEFAULT_EVENT
): string {
    return experiment.resolved_exposure_event || fallbackEvent
}

/**
 * Whether the experiment's analysis excludes test accounts. Mirrors the backend's
 * `resolve_filter_test_accounts`: criteria without the key mean the default, not an opt-out. An
 * experiment stored before creation set the key has none, and so does one whose criteria an
 * update replaced without it. A surface that reads absence as false counts different people than
 * the results do.
 */
export function resolveFilterTestAccounts(exposureCriteria: ExperimentExposureCriteria | null | undefined): boolean {
    return exposureCriteria?.filterTestAccounts ?? true
}

export function exposureEventLabel(event: string): string {
    return event === EXPERIMENT_EXPOSURE_EVENT ? 'Experiment exposure' : 'Feature flag is called'
}

/** The `$feature/<flag_key>` event property that carries the variant for custom exposure events. */
export function featureFlagVariantProperty(featureFlagKey: string): string {
    return `$feature/${featureFlagKey}`
}

function isEventConfig(config: ExperimentExposureConfig): config is ExperimentEventExposureConfig {
    return config.kind === NodeKind.ExperimentEventExposureConfig || 'event' in config
}

export function isDefaultExposureConfig(config: ExperimentExposureConfig): boolean {
    return isEventConfig(config) && config.event === EXPOSURE_DEFAULT_EVENT
}

/** Whether the operator matches the values its positive form does not. Keep in sync with
 * `_NEGATIVE_OPERATOR_COMPLEMENTS` in `posthog/hogql/property.py`. */
function isOperatorNegated(operator: PropertyOperator): boolean {
    return [
        PropertyOperator.IsNot,
        PropertyOperator.NotIn,
        PropertyOperator.IsNotSet,
        PropertyOperator.NotIContains,
        PropertyOperator.NotIContainsMulti,
        PropertyOperator.NotRegex,
        PropertyOperator.NotStartsWith,
        PropertyOperator.NotEndsWith,
        PropertyOperator.NotBetween,
        PropertyOperator.IsCleanedPathNotExact,
        PropertyOperator.SemverNeq,
    ].includes(operator)
}

/**
 * Whether a negated filter in the config leaves out single events while the experiment still counts
 * the person or group that sent them. Event, session and element properties can change from one event
 * to the next. Person properties can too when the team reads them from the events: an event sent before
 * the person identified has no `email`, and a negated filter keeps an event without a value. A cohort
 * filter, and a person filter read from the persons table, leave out the whole person. When the flag
 * counts groups, the group still counts through its other persons. `$feature_flag` names the flag of a
 * flag call event, not a trait of the user. A group-aggregated experiment counts each group by
 * `$group_<index>`, so a filter on that key leaves out the whole group.
 */
export function hasNegatedEventFilter(
    config: ExperimentExposureConfig | undefined,
    groupTypeIndex: number | null | undefined,
    personsOnEventsMode: HogQLQueryModifiers['personsOnEventsMode']
): boolean {
    if (!config || config.kind === NodeKind.ExperimentWarehouseNativeExposureConfig) {
        return false
    }
    const groupKey = groupTypeIndex != null ? `$group_${groupTypeIndex}` : null
    const aggregatesByGroup = groupKey !== null
    const personFilterVaries =
        aggregatesByGroup ||
        personsOnEventsMode === 'person_id_override_properties_on_events' ||
        personsOnEventsMode === 'person_id_no_override_properties_on_events'
    return (config.properties ?? []).some((property) => {
        switch (property.type) {
            case PropertyFilterType.Event:
                return (
                    property.key !== '$feature_flag' &&
                    property.key !== groupKey &&
                    isOperatorNegated(property.operator)
                )
            case PropertyFilterType.Session:
            case PropertyFilterType.Element:
                return isOperatorNegated(property.operator)
            case PropertyFilterType.Person:
                return personFilterVaries && isOperatorNegated(property.operator)
            case PropertyFilterType.Cohort:
                return aggregatesByGroup && isOperatorNegated(property.operator)
            default:
                return false
        }
    })
}

/**
 * The activation event config in effect for the criteria, or undefined when there is none.
 * Activation only composes with the default exposure, so a custom `exposure_config` disables it
 * (mirrors the backend's `has_activation_config`). A config pinning `$experiment_exposure` still
 * counts as default, matching the backend's `is_default_exposure_config`.
 */
export function getActivationConfig(
    exposureCriteria: ExperimentExposureCriteria | undefined
): ExperimentExposureConfig | undefined {
    const activationConfig = exposureCriteria?.activation_config
    if (!activationConfig) {
        return undefined
    }
    const exposureConfig = exposureCriteria?.exposure_config
    if (
        exposureConfig &&
        !(
            isEventConfig(exposureConfig) &&
            [EXPOSURE_DEFAULT_EVENT, EXPERIMENT_EXPOSURE_EVENT].includes(exposureConfig.event)
        )
    ) {
        return undefined
    }
    return activationConfig
}

/**
 * Determines which event and variant property carry the exposure for an experiment.
 *
 * - No exposure config, or a `$feature_flag_called` config: the resolved default event, with the
 *   variant on `$feature_flag_response`.
 * - A custom exposure event: that event, with the variant on `$feature/<flag_key>`.
 * - An action exposure config: `event` is `null` because an action can match multiple events, so no
 *   single event name applies (mirrors the backend returning `None`). Variant is on `$feature/<flag_key>`.
 *
 * `resolvedExposureEvent` is the experiment's server-resolved default (`experimentLogic`'s
 * `resolvedExposureEvent`). Pass it whenever an experiment is in hand — omitting it assumes the
 * pre-rollout default and will name the wrong event for experiments on `$experiment_exposure`.
 */
export function getExposureEventAndProperty({
    featureFlagKey,
    exposureCriteria,
    resolvedExposureEvent = EXPOSURE_DEFAULT_EVENT,
}: {
    featureFlagKey: string
    exposureCriteria: ExperimentExposureCriteria | undefined
    resolvedExposureEvent?: string
}): { event: string | null; variantProperty: string } {
    const exposureConfig = exposureCriteria?.exposure_config

    // No config, or the default `$feature_flag_called` event: variant lives on `$feature_flag_response`.
    if (!exposureConfig || isDefaultExposureConfig(exposureConfig)) {
        return { event: resolvedExposureEvent, variantProperty: EXPOSURE_FEATURE_FLAG_RESPONSE_PROPERTY }
    }

    // Custom exposure event: that event carries the variant on `$feature/<flag_key>`.
    if (isEventConfig(exposureConfig)) {
        return { event: exposureConfig.event, variantProperty: featureFlagVariantProperty(featureFlagKey) }
    }

    // Action config: actions can match multiple events, so there is no single event to filter on.
    return { event: null, variantProperty: featureFlagVariantProperty(featureFlagKey) }
}
