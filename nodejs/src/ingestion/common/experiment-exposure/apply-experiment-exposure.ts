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

function featurePropertyBytes(properties: Record<string, unknown>): number {
    let bytes = 0
    for (const [key, value] of Object.entries(properties)) {
        if (key.startsWith(FEATURE_PROPERTY_PREFIX)) {
            bytes += key.length + serializedBytes(value) + 4
        }
    }
    return bytes
}

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

function exposureEventFor(event: ProcessedEvent, service: ExperimentExposureService): ProcessedEvent | null {
    const properties = event.properties ?? {}
    const classification = classifyFlagCalledEvent(properties)

    if (classification.kind !== 'experiment') {
        experimentExposureEventsTotal.labels(classification.kind).inc()
        return null
    }

    experimentExposureSignalTotal.labels(classification.signal).inc()

    const exposure = buildExposureEvent(event, classification)
    experimentExposureBytesTotal.labels('flag_called').inc(serializedBytes(properties))
    experimentExposureBytesTotal.labels('exposure').inc(serializedBytes(exposure.properties))

    if (!service.shouldWriteForTeam(event.team_id)) {
        experimentExposureEventsTotal.labels('exposure_counted').inc()
        return null
    }

    experimentExposureEventsTotal.labels('exposure_written').inc()
    return exposure
}

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
    return exposureEventFor(event, service)
}
