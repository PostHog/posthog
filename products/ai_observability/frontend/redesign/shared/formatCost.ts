import { humanFriendlyNumber } from 'lib/utils/numbers'

const TRAILING_ZEROS_BEYOND_CENTS = /0{1,2}$/

export function formatCostUsd(costUsd: number): string {
    if (costUsd === 0) {
        return '$0'
    }
    if (costUsd < 0.001) {
        return '<$0.001'
    }
    if (costUsd < 1) {
        return `$${costUsd.toFixed(4).replace(TRAILING_ZEROS_BEYOND_CENTS, '')}`
    }
    return `$${humanFriendlyNumber(costUsd, 2, 2)}`
}
