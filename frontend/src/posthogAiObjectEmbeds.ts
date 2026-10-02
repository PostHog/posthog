import { posthogAiObjectEmbeds as experimentsObjectEmbeds } from 'products/experiments/frontend/posthogAiObjectEmbeds'
import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'
import { posthogAiObjectEmbeds as surveysObjectEmbeds } from 'products/surveys/frontend/posthogAiObjectEmbeds'

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [...experimentsObjectEmbeds, ...surveysObjectEmbeds]
