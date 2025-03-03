import { costsOverrides } from './overrides'
import generatedCosts from './providers.json'
import type { ModelRow } from './types'

export const costs: ModelRow[] = [...generatedCosts, ...costsOverrides]
