import { humanFriendlyNumber } from 'lib/utils/numbers'

export function formatDefinitionCount(count: number, isCapped: boolean): string {
    // `humanFriendlyNumber` calls `toLocaleString`, which throws on a missing count. Callers read this
    // from logic state that is not populated on the first render.
    const rendered = Number.isFinite(count) ? humanFriendlyNumber(count) : '0'
    return `${rendered}${isCapped ? '+' : ''}`
}

export function formatDefinitionCountDelta(total: number, shown: number, isCapped: boolean = false): string {
    const delta = Math.max((total || 0) - (shown || 0), 0)
    return `${humanFriendlyNumber(delta)}${isCapped ? '+' : ''}`
}
