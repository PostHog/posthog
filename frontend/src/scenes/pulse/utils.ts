import { percentage } from 'lib/utils'

export function formatSignedPct(pct: number): string {
    return `${pct >= 0 ? '+' : ''}${percentage(pct, 0)}`
}
