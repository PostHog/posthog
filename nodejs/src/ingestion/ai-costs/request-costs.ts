import bigDecimal from 'js-big-decimal'

import { EventWithProperties } from './process-ai-event'
import { ResolvedModelCost } from './providers/types'

export const calculateRequestCost = (event: EventWithProperties, cost: ResolvedModelCost): string => {
    // If the model doesn't have a request cost component, return 0
    if (cost.cost.request === undefined) {
        return '0'
    }

    // Get the request count, defaulting to 1 only if the model has request pricing
    const requestCount =
        event.properties['$ai_request_count'] !== undefined && event.properties['$ai_request_count'] !== null
            ? event.properties['$ai_request_count']
            : 1

    return bigDecimal.multiply(cost.cost.request, requestCount)
}
