import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ForecastDetectorConfig, ForecastSideRule } from '~/queries/schema/schema-general'

import type { AlertCheck } from '../types'

export type ForecastSide = 'above' | 'below'

// The forecast model's quantile levels. The API refuses any other level.
export const FORECAST_LEVELS: Record<ForecastSide, number[]> = {
    above: [0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99],
    below: [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45],
}

export const DEFAULT_FORECAST_LEVELS: Record<ForecastSide, number> = { above: 0.99, below: 0.01 }

export function getDefaultForecastDetectorConfig(): ForecastDetectorConfig {
    return {
        type: 'forecast',
        above: { quantile: DEFAULT_FORECAST_LEVELS.above },
        below: { quantile: DEFAULT_FORECAST_LEVELS.below },
    }
}

/** The rule each side runs. The API watches both default levels when neither side is set. */
export function getForecastSideRules(config: ForecastDetectorConfig): Partial<Record<ForecastSide, ForecastSideRule>> {
    if (!config.above && !config.below) {
        return {
            above: { quantile: DEFAULT_FORECAST_LEVELS.above },
            below: { quantile: DEFAULT_FORECAST_LEVELS.below },
        }
    }
    return { above: config.above, below: config.below }
}

export function sideRuleHasCondition(rule: ForecastSideRule): boolean {
    return rule.quantile != null || rule.min_relative_change != null || rule.min_absolute_change != null
}

/** How often the model expects a value inside the level: 0.95 above, and 0.05 below, are both 95 in 100. */
export function forecastLevelCoverage(side: ForecastSide, quantile: number): number {
    return Math.round((side === 'above' ? quantile : 1 - quantile) * 100)
}

export function formatForecastLevel(quantile: number): string {
    const percentile = Math.round(quantile * 100)
    return `${percentile}${percentile === 1 ? 'st' : 'th'} percentile`
}

export interface ForecastCheckDetail {
    expected: number
    lower: number
    upper: number
}

export function getForecastCheckDetail(check: AlertCheck): ForecastCheckDetail | null {
    const metadata = check.triggered_metadata
    const { expected, lower, upper } = metadata ?? {}
    if (typeof expected !== 'number' || typeof lower !== 'number' || typeof upper !== 'number') {
        return null
    }
    return { expected, lower, upper }
}

export function formatForecastRange(detail: ForecastCheckDetail): string {
    return `${humanFriendlyNumber(detail.lower)} to ${humanFriendlyNumber(detail.upper)}`
}
