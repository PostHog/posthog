// When the blast-radius readout is aggregated by user, the underlying SQL
// counts `count(DISTINCT persons.id)` (see posthog/models/feature_flag/user_blast_radius.py),
// so the count is matching person profiles, not distinct end users. Calling them
// "users" in the readout misled people who reasonably expected
// `7 unique IDs sharing one email -> 1 user`. Addresses #18109.
export const PERSON_PROFILES_COUNT_LABEL = 'person profiles'

export function blastRadiusCountLabel(
    aggregationGroupTypeIndex: number | null | undefined,
    aggregationLabelFallback: string
): string {
    return aggregationGroupTypeIndex == null ? PERSON_PROFILES_COUNT_LABEL : aggregationLabelFallback
}
