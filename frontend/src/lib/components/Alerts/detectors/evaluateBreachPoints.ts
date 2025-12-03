import {
    AlertDetectorsConfig,
    DetectorConfigType,
    DetectorDirection,
    DetectorGroup,
    DetectorType,
    FilterLogicalOperator,
    InsightThresholdType,
    KMeansDetectorConfig,
    ThresholdDetectorConfig,
    ZScoreDetectorConfig,
} from '~/queries/schema/schema-general'

/**
 * Client-side breach point evaluation for visualization purposes.
 * This is a simplified version of the server-side detector logic.
 */

function evaluateThresholdDetector(config: ThresholdDetectorConfig, data: number[]): number[] {
    const breachIndices: number[] = []
    const bounds = config.bounds

    if (!bounds) {
        return []
    }

    for (let i = 0; i < data.length; i++) {
        const value = data[i]
        if (bounds.lower != null && value < bounds.lower) {
            breachIndices.push(i)
        } else if (bounds.upper != null && value > bounds.upper) {
            breachIndices.push(i)
        }
    }

    return breachIndices
}

function evaluateZScoreDetector(config: ZScoreDetectorConfig, data: number[]): number[] {
    const breachIndices: number[] = []
    const { lookback_periods, z_threshold, direction } = config

    for (let i = 0; i < data.length; i++) {
        // Get historical data for this point
        const histStart = Math.max(0, i - lookback_periods)
        const historicalData = data.slice(histStart, i)

        if (historicalData.length < 2) {
            continue
        }

        // Calculate mean and std
        const mean = historicalData.reduce((a, b) => a + b, 0) / historicalData.length
        const variance = historicalData.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / historicalData.length
        const std = Math.sqrt(variance)

        if (std === 0) {
            continue
        }

        const zScore = (data[i] - mean) / std

        // Check if breaching based on direction
        let isBreach = false
        switch (direction) {
            case DetectorDirection.ABOVE:
                isBreach = zScore > z_threshold
                break
            case DetectorDirection.BELOW:
                isBreach = zScore < -z_threshold
                break
            case DetectorDirection.BOTH:
            default:
                isBreach = Math.abs(zScore) > z_threshold
                break
        }

        if (isBreach) {
            breachIndices.push(i)
        }
    }

    return breachIndices
}

function evaluateKMeansDetector(config: KMeansDetectorConfig, data: number[]): number[] {
    // K-Means is complex to evaluate client-side, returning empty for now
    // In a full implementation, you would run k-means clustering here
    return []
}

function isDetectorGroup(item: DetectorConfigType | DetectorGroup): item is DetectorGroup {
    return 'detectors' in item && Array.isArray(item.detectors)
}

function evaluateSingleDetector(config: DetectorConfigType, data: number[]): number[] {
    switch (config.type) {
        case DetectorType.THRESHOLD:
        case 'threshold':
            return evaluateThresholdDetector(config as ThresholdDetectorConfig, data)
        case DetectorType.ZSCORE:
        case 'zscore':
            return evaluateZScoreDetector(config as ZScoreDetectorConfig, data)
        case DetectorType.KMEANS:
        case 'kmeans':
            return evaluateKMeansDetector(config as KMeansDetectorConfig, data)
        default:
            return []
    }
}

function evaluateDetectorOrGroup(item: DetectorConfigType | DetectorGroup, data: number[]): number[] {
    if (isDetectorGroup(item)) {
        return evaluateGroup(item, data)
    }
    return evaluateSingleDetector(item, data)
}

function evaluateGroup(group: DetectorGroup, data: number[]): number[] {
    if (!group.detectors || group.detectors.length === 0) {
        return []
    }

    const results = group.detectors.map((item) => evaluateDetectorOrGroup(item, data))
    const isAnd = group.type === FilterLogicalOperator.AND_ || group.type === 'AND'

    if (isAnd) {
        // AND: intersection of all breach indices
        if (results.length === 0) {
            return []
        }
        let intersection = new Set(results[0])
        for (let i = 1; i < results.length; i++) {
            const current = new Set(results[i])
            intersection = new Set([...intersection].filter((x) => current.has(x)))
        }
        return Array.from(intersection).sort((a, b) => a - b)
    } else {
        // OR: union of all breach indices
        const union = new Set<number>()
        for (const result of results) {
            for (const idx of result) {
                union.add(idx)
            }
        }
        return Array.from(union).sort((a, b) => a - b)
    }
}

/**
 * Evaluate an alert detector configuration against data and return breach indices.
 */
export function evaluateBreachPoints(
    config: AlertDetectorsConfig | ThresholdDetectorConfig,
    data: number[]
): number[] {
    // Check if it's a single ThresholdDetectorConfig (legacy format)
    if ('bounds' in config && 'threshold_type' in config) {
        return evaluateThresholdDetector(config as ThresholdDetectorConfig, data)
    }

    // It's an AlertDetectorsConfig
    const detectorsConfig = config as AlertDetectorsConfig
    if (!detectorsConfig.groups || detectorsConfig.groups.length === 0) {
        return []
    }

    const results = detectorsConfig.groups.map((item) => evaluateDetectorOrGroup(item, data))
    const isAnd = detectorsConfig.type === FilterLogicalOperator.AND_ || detectorsConfig.type === 'AND'

    if (isAnd) {
        if (results.length === 0) {
            return []
        }
        let intersection = new Set(results[0])
        for (let i = 1; i < results.length; i++) {
            const current = new Set(results[i])
            intersection = new Set([...intersection].filter((x) => current.has(x)))
        }
        return Array.from(intersection).sort((a, b) => a - b)
    } else {
        const union = new Set<number>()
        for (const result of results) {
            for (const idx of result) {
                union.add(idx)
            }
        }
        return Array.from(union).sort((a, b) => a - b)
    }
}
