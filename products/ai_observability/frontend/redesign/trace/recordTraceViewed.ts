import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { addProductIntent } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

export function recordTraceViewed(): void {
    void addProductIntent({
        product_type: ProductKey.AI_OBSERVABILITY,
        intent_context: ProductIntentContext.LLM_ANALYTICS_TRACE_VIEWED,
    })
    // Viewing a trace implies AI events were sent.
    globalSetupLogic
        .findMounted()
        ?.actions.markTaskAsCompleted([SetupTaskId.IngestFirstLlmEvent, SetupTaskId.ViewFirstTrace])
}
