import { humanFriendlyNumber } from 'lib/utils/numbers'

/**
 * Mirrors `LARGE_PROJECT_COUNT_CAP` in `posthog/taxonomy/definition_search.py`. The definition endpoints
 * stop counting at this many rows for large projects, so a count equal to it means "this many or more".
 * A larger count is exact: only large projects are capped, and a capped count never exceeds the cap.
 */
export const DEFINITION_COUNT_CAP = 10_000

export function isCappedDefinitionCount(count: number): boolean {
    return count === DEFINITION_COUNT_CAP
}

export function formatDefinitionCount(count: number): string {
    return isCappedDefinitionCount(count) ? `${humanFriendlyNumber(DEFINITION_COUNT_CAP)}+` : String(count)
}

export function formatDefinitionCountDelta(total: number, shown: number): string {
    const delta = Math.max(total - shown, 0)
    return `${humanFriendlyNumber(delta)}${isCappedDefinitionCount(total) ? '+' : ''}`
}
