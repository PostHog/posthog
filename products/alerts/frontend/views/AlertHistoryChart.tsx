import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    ForecastConditionType,
    ForecastTargetDirection,
    InsightThresholdType,
    TargetByDateForecastConfig,
} from '~/queries/schema/schema-general'

import {
    AlertEvaluationHistoryChart,
    AlertEvaluationThreshold,
} from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'

import type { AlertHistoryChartPoint } from '../logic/alertLogic'
import type { AlertType } from '../types'

export type { AlertHistoryChartPoint }

type ThresholdLineMode = 'value' | 'anomaly_probability'

interface ChartThresholdContext {
    lower: number | null
    upper: number | null
    boundType: 'absolute' | 'percentage'
    lineMode: ThresholdLineMode
}

function getChartThresholdContext(alert: AlertType, chartPlotsAnomalyScore: boolean): ChartThresholdContext | null {
    const detectorConfig = alert.detector_config
    if (detectorConfig && typeof detectorConfig === 'object' && 'type' in detectorConfig) {
        if (detectorConfig.type === 'ensemble') {
            return null
        }
        if (detectorConfig.type === 'threshold') {
            const upper =
                'upper_bound' in detectorConfig && typeof detectorConfig.upper_bound === 'number'
                    ? detectorConfig.upper_bound
                    : null
            const lower =
                'lower_bound' in detectorConfig && typeof detectorConfig.lower_bound === 'number'
                    ? detectorConfig.lower_bound
                    : null
            if (upper == null && lower == null) {
                return null
            }
            return { lower, upper, boundType: 'absolute', lineMode: 'value' }
        }
        if (
            chartPlotsAnomalyScore &&
            'threshold' in detectorConfig &&
            typeof detectorConfig.threshold === 'number' &&
            !Number.isNaN(detectorConfig.threshold)
        ) {
            return {
                lower: null,
                upper: detectorConfig.threshold,
                boundType: 'absolute',
                lineMode: 'anomaly_probability',
            }
        }
        return null
    }

    const thresholdConfiguration = alert.threshold?.configuration
    const lower = thresholdConfiguration?.bounds?.lower ?? null
    const upper = thresholdConfiguration?.bounds?.upper ?? null
    if (lower == null && upper == null) {
        return null
    }
    return {
        lower,
        upper,
        boundType: thresholdConfiguration?.type === InsightThresholdType.PERCENTAGE ? 'percentage' : 'absolute',
        lineMode: 'value',
    }
}

function formatThresholdLabel(value: number, context: ChartThresholdContext): string {
    if (context.lineMode === 'anomaly_probability') {
        return `${Math.round(value * 100)}% probability`
    }
    if (context.boundType === 'percentage') {
        return `${humanFriendlyNumber(value * 100)}% change`
    }
    return humanFriendlyNumber(value)
}

function buildThresholds(context: ChartThresholdContext | null): AlertEvaluationThreshold[] {
    if (!context) {
        return []
    }
    const thresholds: AlertEvaluationThreshold[] = []
    if (context.upper != null) {
        thresholds.push({
            direction: 'upper',
            value: context.upper,
            label: `Upper (${formatThresholdLabel(context.upper, context)})`,
        })
    }
    if (context.lower != null) {
        thresholds.push({
            direction: 'lower',
            value: context.lower,
            label: `Lower (${formatThresholdLabel(context.lower, context)})`,
        })
    }
    return thresholds
}

/** A target alert is evaluated against its target and direction, never against threshold bounds,
 * which survive on an alert converted from threshold mode. Draw the target on the side the
 * evaluation compares against, so the chart states the rule that actually runs. */
function forecastTargetThresholds(config: TargetByDateForecastConfig): AlertEvaluationThreshold[] {
    if (!Number.isFinite(config.target)) {
        return []
    }
    return [
        {
            direction: config.target_direction === ForecastTargetDirection.AT_MOST ? 'upper' : 'lower',
            value: config.target,
            label: `Target (${humanFriendlyNumber(config.target)})`,
        },
    ]
}

export function getAlertHistoryThresholds(
    alert: AlertType,
    chartPlotsAnomalyScore: boolean
): AlertEvaluationThreshold[] {
    if (alert.forecast_config?.condition === ForecastConditionType.TARGET_BY_DATE) {
        return forecastTargetThresholds(alert.forecast_config)
    }
    return buildThresholds(getChartThresholdContext(alert, chartPlotsAnomalyScore))
}

export function AlertHistoryChart({
    points,
    valueLabel,
    alert,
    chartPlotsAnomalyScore,
    historyLimit,
    checksTotal,
}: {
    points: AlertHistoryChartPoint[]
    valueLabel: string
    alert: AlertType
    chartPlotsAnomalyScore: boolean
    historyLimit: number
    checksTotal?: number | null
}): JSX.Element {
    return (
        <AlertEvaluationHistoryChart
            points={points}
            valueLabel={valueLabel}
            thresholds={getAlertHistoryThresholds(alert, chartPlotsAnomalyScore)}
            historyLimit={historyLimit}
            evaluationsTotal={checksTotal}
            evaluationNoun="check"
            tableAvailable
            classifyUnusualWithoutThresholds
        />
    )
}
