import backupCosts from './backup-llm-provider-costs.json'
import { embeddingCosts } from './embeddings'
import primaryCosts from './llm-provider-costs.json'
import { manualCosts } from './manual-providers'
import type { ModelRow } from './types'

// Primary costs from llm-provider-costs.json plus manual costs
export const primaryCostsByModel: Record<string, ModelRow> = {}
export const primaryCostsList: ModelRow[] = [...primaryCosts, ...manualCosts]

for (const cost of primaryCostsList) {
    primaryCostsByModel[cost.model.toLowerCase()] = cost
}

// Backup costs from backup-llm-provider-costs.json plus manual and embedding costs
export const backupCostsByModel: Record<string, ModelRow> = {}

for (const cost of [...backupCosts, ...manualCosts, ...embeddingCosts]) {
    backupCostsByModel[cost.model.toLowerCase()] = cost
}
