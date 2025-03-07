import { costsOverrides } from './overrides'
import generatedCosts from './providers.json'
import type { ModelRow } from './types'

export const costsByModel: Record<string, ModelRow> = {}

for (const cost of [...generatedCosts, ...costsOverrides]) {
    // NOTE: This is done in a loop with overrides after ensuring that they are applied
    costsByModel[cost.model] = cost
}
