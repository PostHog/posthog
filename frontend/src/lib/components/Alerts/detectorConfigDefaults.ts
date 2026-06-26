import {
    AlertCalculationInterval,
    DetectorConfig,
    EnsembleDetectorConfig,
    EnsembleOperator,
    SingleDetectorConfig,
} from '~/queries/schema/schema-general'

export const DEFAULT_ANOMALY_DETECTION_THRESHOLD = 0.95

/** Default window size based on how often the alert checks. */
export function getDefaultWindow(interval?: AlertCalculationInterval): number {
    switch (interval) {
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return 672
        case AlertCalculationInterval.HOURLY:
            return 168
        case AlertCalculationInterval.WEEKLY:
            return 26
        case AlertCalculationInterval.MONTHLY:
            return 12
        default:
            return 90
    }
}

export function getDefaultAnomalyDetectorConfig(interval?: AlertCalculationInterval): DetectorConfig {
    return {
        type: 'zscore',
        threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
        window: getDefaultWindow(interval),
        preprocessing: { diffs_n: 1 },
    }
}

export function getDefaultSingleDetectorConfigs(window: number): Record<string, SingleDetectorConfig> {
    return {
        zscore: {
            type: 'zscore',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1 },
        },
        mad: {
            type: 'mad',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1 },
        },
        iqr: { type: 'iqr', multiplier: 1.5, window },
        threshold: { type: 'threshold' },
        ecod: { type: 'ecod', threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD, window },
        copod: { type: 'copod', threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD, window },
        isolation_forest: {
            type: 'isolation_forest',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            n_estimators: 100,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        knn: {
            type: 'knn',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            n_neighbors: 5,
            method: 'largest',
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        lof: {
            type: 'lof',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            n_neighbors: 20,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        hbos: { type: 'hbos', threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD, n_bins: 10, window },
        ocsvm: {
            type: 'ocsvm',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        pca: {
            type: 'pca',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
    }
}

export function getDefaultEnsembleDetectorConfig(window: number): EnsembleDetectorConfig {
    return {
        type: 'ensemble',
        operator: EnsembleOperator.AND,
        detectors: [
            {
                type: 'zscore',
                threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
                window,
                preprocessing: { diffs_n: 1 },
            },
            {
                type: 'mad',
                threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
                window,
                preprocessing: { diffs_n: 1 },
            },
        ],
    }
}
