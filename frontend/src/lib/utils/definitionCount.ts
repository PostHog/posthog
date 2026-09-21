import { humanFriendlyNumber } from 'lib/utils/numbers'

/**
 * The definition list endpoints stop counting at a cap on large projects and say so with
 * `count_is_capped`. Read that flag rather than comparing the count to a number: a project holding
 * exactly the cap has an exact count, and the cap itself is the server's to choose.
 */
export interface CappableCount {
    count?: number | null
    count_is_capped?: boolean
}

export function definitionCountIsCapped(response: CappableCount | null | undefined): boolean {
    return response?.count_is_capped === true
}

export function formatDefinitionCount(count: number, isCapped: boolean): string {
    return `${humanFriendlyNumber(count)}${isCapped ? '+' : ''}`
}

export function formatDefinitionCountDelta(total: number, shown: number, isCapped: boolean = false): string {
    return `${humanFriendlyNumber(Math.max(total - shown, 0))}${isCapped ? '+' : ''}`
}
