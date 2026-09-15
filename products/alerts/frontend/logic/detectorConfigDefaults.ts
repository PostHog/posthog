import { AlertCalculationInterval, SingleDetectorConfig, ZScoreDetectorConfig } from '~/queries/schema/schema-general'

export const DEFAULT_ANOMALY_DETECTION_THRESHOLD = 0.95

/** Default window size in data points based on how often the alert checks.
 * Every 15 minutes: 672 (7 days), Hourly: 168 (7 days), Daily: 90 (90 days),
 * Weekly: 26 (6 months), Monthly: 12 (1 year). */
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

export function getDefaultZScoreDetectorConfig(window: number): ZScoreDetectorConfig {
    return {
        type: 'zscore',
        threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
        window,
        preprocessing: { diffs_n: 1 },
    }
}

/** The model reports its own confidence, so this is the confidence the alert requires before firing. */
export const DEFAULT_LLM_DETECTION_CONFIDENCE = 0.7
export const MAX_LLM_DETECTOR_WINDOW = 400

export function getDefaultLLMDetectorConfig(window: number): SingleDetectorConfig {
    return {
        type: 'llm',
        threshold: DEFAULT_LLM_DETECTION_CONFIDENCE,
        window: Math.min(window, MAX_LLM_DETECTOR_WINDOW),
    }
}

export function getDefaultAnomalyDetectorConfig(interval?: AlertCalculationInterval): SingleDetectorConfig {
    return getDefaultZScoreDetectorConfig(getDefaultWindow(interval))
}
