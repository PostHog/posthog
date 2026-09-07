import { ForecastTargetDirection, InsightsThresholdBounds } from '~/queries/schema/schema-general'

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
