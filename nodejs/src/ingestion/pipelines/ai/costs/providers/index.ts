import openRouterCostsRaw from './llm-costs.json'
import { manualCosts } from './manual-providers'
import type { ModelCostRow } from './types'

const openRouterCosts = openRouterCostsRaw as ModelCostRow[]

export const openRouterCostsByModel: Record<string, ModelCostRow> = {}

for (const cost of openRouterCosts) {
    openRouterCostsByModel[cost.model.toLowerCase()] = cost
}

export const manualCostsByModel: Record<string, ModelCostRow | undefined> = {}

for (const cost of manualCosts) {
    manualCostsByModel[cost.model.toLowerCase()] = cost
}
