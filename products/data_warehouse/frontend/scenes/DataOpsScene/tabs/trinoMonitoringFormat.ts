import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

export function stateLabel(state: string): string {
    const normalized = state.replaceAll('_', ' ')
    return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

export function duration(milliseconds: number): string {
    return humanFriendlyDuration(milliseconds / 1000, { secondsPrecision: 2 }) || '0s'
}

export function withLimit(value: number, limit: number): string {
    return limit > 0 ? `${humanFriendlyNumber(value)} / ${humanFriendlyNumber(limit)}` : humanFriendlyNumber(value)
}
