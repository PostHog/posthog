import { posthogAiObjectEmbeds as errorTrackingObjectEmbeds } from 'products/error_tracking/frontend/posthogAiObjectEmbeds'
import { posthogAiObjectEmbeds as experimentsObjectEmbeds } from 'products/experiments/frontend/posthogAiObjectEmbeds'
import { posthogAiObjectEmbeds as personsObjectEmbeds } from 'products/persons/frontend/posthogAiObjectEmbeds'
import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'
import { posthogAiObjectEmbeds as surveysObjectEmbeds } from 'products/surveys/frontend/posthogAiObjectEmbeds'

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [
    ...errorTrackingObjectEmbeds,
    ...experimentsObjectEmbeds,
    ...personsObjectEmbeds,
    ...surveysObjectEmbeds,
]
