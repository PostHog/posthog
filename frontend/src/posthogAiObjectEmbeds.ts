import { posthogAiObjectEmbeds as experimentsObjectEmbeds } from 'products/experiments/frontend/posthogAiObjectEmbeds'
import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [...experimentsObjectEmbeds]
