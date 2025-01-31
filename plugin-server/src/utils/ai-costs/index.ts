import { costs as anthropicCosts } from './anthropic'
import { costs as cohereCosts } from './cohere'
import { costs as deepseekCosts } from './deepseek'
import { costs as googleCosts } from './google'
import { costs as mistralaiCosts } from './mistralai'
import { costs as openaiCosts } from './openai'
import { costs as perplexityCosts } from './perplexity'
import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    ...openaiCosts,
    ...anthropicCosts,
    ...googleCosts,
    ...deepseekCosts,
    ...perplexityCosts,
    ...cohereCosts,
    ...mistralaiCosts,
]
