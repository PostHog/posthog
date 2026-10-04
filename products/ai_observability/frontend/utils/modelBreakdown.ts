import { escapeRegex } from 'lib/utils/actions'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

// The SDKs write `$ai_model` through untouched, so one model reaches us under several
// spellings once a project adds a gateway or a second provider: `gpt-5` and `openai/gpt-5`,
// `gemini-3-flash` and `models/gemini-3-flash`, `GLM-5.3` and `glm-5.3`. Event properties
// cannot be rewritten after ingestion, so a breakdown on the raw value shows one model as
// several bars forever. Fold the provider prefix and the case at query time instead.
// Kept in sync with NORMALIZED_MODEL_BREAKDOWN_HOGQL in
// products/ai_observability/backend/model_breakdown.py.
export const NORMALIZED_MODEL_BREAKDOWN_HOGQL = "lower(replaceRegexpOne(toString(properties.$ai_model), '^.*/', ''))"

export const MODEL_BREAKDOWN_DESCRIPTION =
    'Model names are folded to lowercase without the provider prefix, so openai/gpt-5 and gpt-5 count as one model.'

/**
 * Filter that reaches every raw `$ai_model` value behind one normalized breakdown value.
 * An exact filter would miss the prefixed spellings, and a contains filter would also pull
 * in longer names, so `gpt-5` would drag in `gpt-5-mini`.
 */
export function normalizedModelPropertyFilter(normalizedModel: string): AnyPropertyFilter {
    return {
        type: PropertyFilterType.Event,
        key: '$ai_model',
        operator: PropertyOperator.Regex,
        value: `(?i)(^|/)${escapeRegex(normalizedModel)}$`,
    }
}
