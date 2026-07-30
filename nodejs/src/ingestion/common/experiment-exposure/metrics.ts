import { Counter } from 'prom-client'

export const experimentExposureEventsTotal = new Counter({
    name: 'ingestion_experiment_exposure_events_total',
    help: 'Classification outcomes for $feature_flag_called events considered for exposure duplication',
    labelNames: ['outcome'],
})

export const experimentExposureSignalTotal = new Counter({
    name: 'ingestion_experiment_exposure_signal_total',
    help: 'Which signal classified a $feature_flag_called event as experiment-related',
    labelNames: ['signal'],
})

export const experimentExposureBytesTotal = new Counter({
    name: 'ingestion_experiment_exposure_bytes_total',
    help: 'Serialized property bytes attributable to each half of the exposure migration',
    labelNames: ['kind'],
})

export const experimentExposureMappingTotal = new Counter({
    name: 'ingestion_experiment_exposure_mapping_total',
    help: 'Events carrying $feature/* properties that map to a non-empty $experiment_exposures value',
    labelNames: ['outcome'],
})
