import bigDecimal from 'js-big-decimal'

import { EventWithProperties } from '~/ingestion/pipelines/ai/process-ai-event'

import { finiteNumberOrUndefined } from './cost-utils'
import { ResolvedModelCost } from './providers/types'

export const calculateRequestCost = (event: EventWithProperties, cost: ResolvedModelCost): string => {
    // If the model doesn't have a request cost component, return 0
    if (cost.cost.request === undefined) {
        return '0'
    }

    // An unusable count is treated like an absent one — the model bills per
    // request, so still charge for the single request we know happened.
    const requestCount = finiteNumberOrUndefined(event.properties['$ai_request_count']) ?? 1

    return bigDecimal.multiply(cost.cost.request, requestCount)
}
