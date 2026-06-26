import { AlertCalculationInterval, SingleDetectorConfig } from '~/queries/schema/schema-general'

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

export function getDefaultZScoreDetectorConfig(window: number): SingleDetectorConfig {
    return {
        type: 'zscore',
        threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
        window,
        preprocessing: { diffs_n: 1 },
    }
}

export function getDefaultAnomalyDetectorConfig(interval?: AlertCalculationInterval): SingleDetectorConfig {
    return getDefaultZScoreDetectorConfig(getDefaultWindow(interval))
}
