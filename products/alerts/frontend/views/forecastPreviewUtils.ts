import type { GoalLineConfig } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastTargetDirection,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'

import { ForecastTargetProjectionApi } from 'products/alerts/frontend/generated/api.schemas'
import { hasThresholdBounds, valueBreachesBounds } from 'products/alerts/frontend/logic/alertPreviewShared'

export function findFirstCrossing(forecastYhat: number[], bounds: InsightsThresholdBounds | null): number | null {
    if (!hasThresholdBounds(bounds)) {
        return null
    }
    for (let index = 0; index < forecastYhat.length; index++) {
        if (valueBreachesBounds(forecastYhat[index], bounds)) {
            return index
        }
    }
    return null
}

/** The backend tests the latest completed value against the bounds and fires on it before it runs
 *  the forecast engine (`_actual_breach` in products/alerts/backend/evaluation/forecast.py), so the
 *  preview has to make the same test. Without it the preview reports all clear for an alert that
 *  fires on the next evaluation. Only future-breach alerts get this pre-check, because a target
 *  alert always waits for the forecast. */
export function findObservedBreach(
    data: number[],
    bounds: InsightsThresholdBounds | null
): { index: number; value: number } | null {
    if (!hasThresholdBounds(bounds) || data.length === 0) {
        return null
    }
    const index = data.length - 1
    const value = data[index]
    return valueBreachesBounds(value, bounds) ? { index, value } : null
}

/** Names the bucket the backend evaluated. History and forecast dates are bucket timestamps in
 *  project-local wall time with no zone attached, so formatting them as parsed keeps the bucket
 *  intact. An hourly insight puts up to 24 buckets on one calendar day, so the label has to keep
 *  the hour to say which bucket the value belongs to. */
export function bucketLabel(value: string, interval: string | null | undefined): string {
    const parsed = dayjs(value)
    if (!parsed.isValid()) {
        return value
    }
    return parsed.format(interval === 'hour' ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY')
}

export function targetSummary(projection: ForecastTargetProjectionApi, direction: ForecastTargetDirection): string {
    if (!projection.misses_target) {
        return direction === ForecastTargetDirection.AT_MOST
            ? 'On track to stay at or under the target'
            : 'On track to reach the target'
    }
    return direction === ForecastTargetDirection.AT_MOST
        ? 'Projected to finish above the target'
        : 'Projected to finish below the target'
}

/** The threshold and target lines for the preview chart. They go through the chart's `goalLines`
 *  config rather than an overlay child, because only `goalLines` stretches the value axis — a line
 *  outside the forecast range would otherwise be clipped away and never drawn. */
export function forecastGoalLines(
    thresholdBounds: InsightsThresholdBounds | null,
    forecastConfig: ForecastConfig
): GoalLineConfig[] {
    const lines: GoalLineConfig[] = []
    if (thresholdBounds?.upper != null) {
        lines.push({
            value: thresholdBounds.upper,
            label: `More than ${humanFriendlyNumber(thresholdBounds.upper)}`,
            labelPosition: 'start',
            color: 'var(--danger)',
        })
    }
    if (thresholdBounds?.lower != null) {
        lines.push({
            value: thresholdBounds.lower,
            label: `Less than ${humanFriendlyNumber(thresholdBounds.lower)}`,
            labelPosition: 'start',
            color: 'var(--danger)',
        })
    }
    if (forecastConfig.condition === ForecastConditionType.TARGET_BY_DATE) {
        lines.push({
            value: forecastConfig.target,
            label: `Target ${humanFriendlyNumber(forecastConfig.target)}`,
            labelPosition: 'start',
        })
    }
    return lines
}
