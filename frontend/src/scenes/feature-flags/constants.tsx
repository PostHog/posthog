import { Link } from '@posthog/lemon-ui'

export const COHORT_BEHAVIORAL_LIMITATIONS_URL =
    'https://posthog.com/docs/feature-flags/common-questions#why-cant-i-use-a-cohort-with-behavioral-filters-in-my-feature-flag'

/**
 * Resolves a condition set's effective aggregation group type index, mirroring the backend's
 * `effective_aggregation` (rust/feature-flags/src/flags/flag_property_group.rs). The per-condition
 * field has three states that must stay distinct — `??` would wrongly collapse the first two:
 * - `undefined` — not set, inherit the flag-level (global) index
 * - `null` — explicitly target users, overriding the global group index
 * - number — explicitly target that group type
 */
export function resolveAggregationGroupTypeIndex(
    conditionGroupTypeIndex: number | null | undefined,
    flagLevelGroupTypeIndex: number | null | undefined
): number | null {
    return (conditionGroupTypeIndex !== undefined ? conditionGroupTypeIndex : flagLevelGroupTypeIndex) ?? null
}

export const MATCHING_ESTIMATE_TOOLTIP = (
    <>
        <div>
            A user may have{' '}
            <Link to="https://posthog.com/docs/data/persons#duplicate-person-profiles" target="_blank">
                multiple profiles
            </Link>
        </div>
        <div className="mt-1">
            Estimated from{' '}
            <Link to="https://posthog.com/docs/data/anonymous-vs-identified-events" target="_blank">
                identified users
            </Link>{' '}
            only. Anonymous visitors can still match this flag, so the actual number may be higher.
        </div>
    </>
)
