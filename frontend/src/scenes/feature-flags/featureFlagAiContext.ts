import { FeatureFlagType } from '~/types'

import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

// The backend rejects a text attachment longer than this and fails the whole send with a 400
// (MAX_TEXT_LENGTH in products/posthog_ai/backend/context_wrapper.py), so an oversized flag has to
// lose detail here rather than break the user's message.
const MAX_TARGETING_VALUE_LENGTH = 4096

// A flag's description is free text with no length limit of its own, so it could otherwise eat the
// whole budget above on its own.
const MAX_DESCRIPTION_LENGTH = 400

/**
 * Describes a saved flag to PostHog AI: a keyed reference that renders as the composer chip, plus a
 * separate keyless item carrying the targeting as JSON.
 *
 * These have to stay two items. `formatItem` in posthogContextBlock renders a keyed item as its
 * type, key, and label alone and never reads `value`, so folding the JSON into the reference would
 * drop the targeting before it reached the agent.
 */
export function featureFlagContextItems(featureFlag: FeatureFlagType): AttachedContextItem[] {
    return [
        // `name` on a flag is the description, so the key is the only display name available here.
        { type: 'feature_flag', key: featureFlag.key, label: featureFlag.key },
        { type: 'feature_flag_targeting', label: 'Release conditions', value: targetingValue(featureFlag) },
    ]
}

function targetingValue(featureFlag: FeatureFlagType): string {
    const filters = featureFlag.filters
    const identity = {
        key: featureFlag.key,
        description: featureFlag.name.slice(0, MAX_DESCRIPTION_LENGTH),
        active: featureFlag.active,
        // Whether the flag counts persons or a group type, which decides what "who matches?" means.
        aggregation_group_type_index: filters?.aggregation_group_type_index ?? null,
        // The matcher evaluates all three ahead of the release conditions, so an agent reading only
        // those overcounts a flag behind a holdout or an early access gate.
        holdout: filters?.holdout ?? null,
    }

    const full = JSON.stringify({
        ...identity,
        multivariate: filters?.multivariate ?? null,
        super_groups: filters?.super_groups ?? null,
        holdout_groups: filters?.holdout_groups ?? null,
        release_conditions: filters?.groups ?? [],
    })
    if (full.length <= MAX_TARGETING_VALUE_LENGTH) {
        return full
    }

    // Property filters are what blow the budget, because a single condition can hold hundreds of
    // pasted values. Variant keys and the condition counts still describe the flag's shape, and the
    // agent can read the saved flag by key when it needs the filters themselves.
    return JSON.stringify({
        ...identity,
        variant_keys: filters?.multivariate?.variants.map((variant) => variant.key) ?? null,
        release_condition_count: filters?.groups?.length ?? 0,
        super_condition_count: filters?.super_groups?.length ?? 0,
        holdout_condition_count: filters?.holdout_groups?.length ?? 0,
        conditions_omitted: 'Too large to attach. Read the saved flag to see the property filters.',
    })
}
