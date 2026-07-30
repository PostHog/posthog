import { ProcessedEvent } from '~/types'

import {
    EXPERIMENT_EXPOSURES_PROPERTY,
    ExperimentExposureService,
    FEATURE_FLAG_CALLED_EVENT,
    FEATURE_PROPERTY_PREFIX,
    buildExperimentExposuresProperty,
    buildExposureEvent,
    classifyFlagCalledEvent,
    serializedBytes,
} from './experiment-exposure-service'
import {
    experimentExposureBytesTotal,
    experimentExposureEventsTotal,
    experimentExposureMappingTotal,
    experimentExposureSignalTotal,
} from './metrics'

/**
 * Serialized size of the `$feature/*` properties this event carries, which is
 * what stripping them in a later phase would save.
 */
function featurePropertyBytes(properties: Record<string, unknown>): number {
    let bytes = 0
    for (const [key, value] of Object.entries(properties)) {
        if (key.startsWith(FEATURE_PROPERTY_PREFIX)) {
            // Approximates the JSON framing per key: two quotes, a colon, a comma.
            bytes += key.length + serializedBytes(value) + 4
        }
    }
    return bytes
}

/**
 * Adds the `$experiment_exposures` map to any event carrying `$feature/*`
 * properties, so that experiments with custom exposure criteria have a carrier
 * to read variants from once those per-flag properties are stripped.
 *
 * Purely additive: nothing is removed here. Stripping `$feature/*` is a separate,
 * later phase, because those properties are also a customer-facing filtering
 * surface in regular insights, not just an experiments input.
 *
 * Counts run in every mode. Mutation only happens for teams enabled for writes.
 */
function applyExposureMapping(event: ProcessedEvent, service: ExperimentExposureService): void {
    const properties = event.properties ?? {}
    const exposures = buildExperimentExposuresProperty(properties)
    if (!exposures) {
        return
    }

    experimentExposureMappingTotal.labels('mapped').inc()
    experimentExposureBytesTotal.labels('feature_properties').inc(featurePropertyBytes(properties))
    experimentExposureBytesTotal.labels('exposures_map').inc(serializedBytes(exposures))

    if (service.shouldWriteForTeam(event.team_id)) {
        properties[EXPERIMENT_EXPOSURES_PROPERTY] = exposures
        event.properties = properties
    }
}

/**
 * Classifies a $feature_flag_called event and returns the duplicate
 * $experiment_exposure event to emit alongside it, or null to emit nothing.
 *
 * In `metrics` mode this always returns null: it records what the duplication
 * would have produced without touching the event stream, which is how the
 * migration is sized before any team is opted in. Only `enabled` mode plus an
 * allowlisted team yields an event.
 */
function exposureEventFor(event: ProcessedEvent, service: ExperimentExposureService): ProcessedEvent | null {
    const properties = event.properties ?? {}
    const classification = classifyFlagCalledEvent(properties)

    if (classification.kind !== 'experiment') {
        experimentExposureEventsTotal.labels(classification.kind).inc()
        return null
    }

    experimentExposureSignalTotal.labels(classification.signal).inc()

    const exposure = buildExposureEvent(event, classification)
    // Counted in every mode, including metrics, because the point of the counters
    // is the saving we would get if the source event were dropped and this
    // duplicate kept.
    experimentExposureBytesTotal.labels('flag_called').inc(serializedBytes(properties))
    experimentExposureBytesTotal.labels('exposure').inc(serializedBytes(exposure.properties))

    if (!service.shouldWriteForTeam(event.team_id)) {
        experimentExposureEventsTotal.labels('exposure_counted').inc()
        return null
    }

    experimentExposureEventsTotal.labels('exposure_written').inc()
    return exposure
}

/**
 * Runs both halves of the exposure migration for one processed event: the
 * `$experiment_exposures` mapping that applies to every event, and the
 * `$experiment_exposure` duplicate that applies only to $feature_flag_called.
 *
 * Returns the duplicate event to emit alongside the original, or null.
 */
export function applyExperimentExposure(
    event: ProcessedEvent,
    service: ExperimentExposureService | undefined
): ProcessedEvent | null {
    if (!service) {
        return null
    }

    applyExposureMapping(event, service)

    if (event.event !== FEATURE_FLAG_CALLED_EVENT) {
        return null
    }
    // Runs after the mapping so the duplicate inherits $experiment_exposures.
    return exposureEventFor(event, service)
}
