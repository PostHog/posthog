import { embeddingCosts } from './embeddings'
import generatedCosts from './generated-providers.json'
import { manualCosts } from './manual-providers'
import type { ModelRow } from './types'

export const costsByModel: Record<string, ModelRow> = {}

for (const cost of [...generatedCosts, ...manualCosts, ...embeddingCosts]) {
    // NOTE: This is done in a loop with overrides after ensuring that they are applied
    costsByModel[cost.model] = cost
}
