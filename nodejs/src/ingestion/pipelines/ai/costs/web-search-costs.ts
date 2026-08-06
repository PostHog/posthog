import bigDecimal from 'js-big-decimal'

import { EventWithProperties } from '~/ingestion/pipelines/ai/process-ai-event'

import { finiteNumberOrUndefined } from './cost-utils'
import { ResolvedModelCost } from './providers/types'

export const calculateWebSearchCost = (event: EventWithProperties, cost: ResolvedModelCost): string => {
    // If the model doesn't have a web search cost component, return 0
    if (cost.cost.web_search === undefined) {
        return '0'
    }

    // Only calculate if web search count is explicitly provided (no default)
    const webSearchCount = finiteNumberOrUndefined(event.properties['$ai_web_search_count'])

    if (webSearchCount === undefined) {
        return '0'
    }

    return bigDecimal.multiply(cost.cost.web_search, webSearchCount)
}
