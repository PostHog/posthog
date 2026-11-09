import { FEATURE_FLAGS } from 'lib/constants'

// The `control` variant is truthy, so a plain flag check would give control the fuzzy search too.
export function fuzzyEventSearchEnabled(
    featureFlags: Record<string, boolean | string | undefined>,
    allowNonCapturedEvents: boolean | undefined
): boolean {
    return featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_FUZZY_EVENT_SEARCH] === 'test' && !allowNonCapturedEvents
}
