import { costs as anthropicCosts } from './anthropic'
import { costs as anthropicOverrides } from './anthropic_overrides'
import { costs as cohereCosts } from './cohere'
import { costs as deepseekCosts } from './deepseek'
import { costs as googleCosts } from './google'
import { costs as metaLlamaCosts } from './meta-llama'
import { costs as mistralaiCosts } from './mistralai'
import { costs as openaiCosts } from './openai'
import { costs as openaiOverrides } from './openai_overrides'
import { costs as perplexityCosts } from './perplexity'
import type { ModelRow } from './types'

export const costs: ModelRow[] = [
    ...openaiCosts,
    ...openaiOverrides,
    ...anthropicCosts,
    ...anthropicOverrides,
    ...googleCosts,
    ...deepseekCosts,
    ...perplexityCosts,
    ...cohereCosts,
    ...mistralaiCosts,
    ...metaLlamaCosts,
]
