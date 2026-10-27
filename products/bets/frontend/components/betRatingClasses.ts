import type { BetRating } from '../lib/betPerformance'

export const BET_RATING_CLASSES: Record<BetRating, string> = {
    bad: 'text-warning-foreground',
    meh: 'text-muted-foreground',
    good: 'text-success-foreground',
    amazing: 'text-success-foreground',
}
