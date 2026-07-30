import { Counter } from 'prom-client'

export const experimentExposureEventsTotal = new Counter({
    name: 'ingestion_experiment_exposure_events_total',
    help: 'Classification outcomes for $feature_flag_called events considered for exposure duplication',
    // 'exposure_written' | 'exposure_counted' | 'not_experiment' | 'unclassifiable'
    labelNames: ['outcome'],
})

export const experimentExposureSignalTotal = new Counter({
    name: 'ingestion_experiment_exposure_signal_total',
    help: 'Which signal classified a $feature_flag_called event as experiment-related',
    // 'has_experiment_property' | 'multivariate_response'
    labelNames: ['signal'],
})

/**
 * Byte accounting for the migration's end state, where $feature_flag_called is
 * dropped and only $experiment_exposure is kept. `flag_called` is what dropping
 * the source event would save; `exposure` is what the duplicate costs. The net
 * saving is the difference, so both must be counted on the same events for the
 * ratio to mean anything.
 *
 * Sizes are the serialized property payload, which tracks the dominant term in
 * the ClickHouse row but is neither the compressed on-disk size nor the full
 * row. Treat these as a relative signal, not a storage forecast.
 */
export const experimentExposureBytesTotal = new Counter({
    name: 'ingestion_experiment_exposure_bytes_total',
    help: 'Serialized property bytes attributable to each half of the exposure migration',
    // 'flag_called' | 'exposure' | 'feature_properties' | 'exposures_map'
    labelNames: ['kind'],
})

export const experimentExposureMappingTotal = new Counter({
    name: 'ingestion_experiment_exposure_mapping_total',
    help: 'Events carrying $feature/* properties that map to a non-empty $experiment_exposures value',
    // 'mapped'
    labelNames: ['outcome'],
})
