import { LemonSelectOptions } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

const DEFAULT_RECORDINGS_LOOKBACK_DAYS = 3

/**
 * Recordings default to a 3-day lookback window, which misses any event whose last
 * occurrence is older than that. Deep links from event definitions know when the
 * event was last seen, so widen the window to cover it instead of guaranteeing an
 * empty "View recordings" result for infrequent events.
 */
export function recordingsDateFromForLastSeen(lastSeenAt?: string | null): string {
    if (!lastSeenAt) {
        return `-${DEFAULT_RECORDINGS_LOOKBACK_DAYS}d`
    }
    const daysSinceLastSeen = dayjs().diff(dayjs(lastSeenAt), 'day')
    return `-${Math.max(daysSinceLastSeen + 1, DEFAULT_RECORDINGS_LOOKBACK_DAYS)}d`
}

type VerifiedFilterOption = 'all' | 'verified' | 'unverified'

export const verifiedOptions: LemonSelectOptions<VerifiedFilterOption> = [
    { value: 'all', label: 'All' },
    { value: 'verified', label: 'Verified only' },
    { value: 'unverified', label: 'Unverified only' },
]

export function verifiedFilterValue(verified: boolean | undefined): VerifiedFilterOption {
    if (verified === true) {
        return 'verified'
    }
    if (verified === false) {
        return 'unverified'
    }
    return 'all'
}

export function verifiedFilterFromOption(option: VerifiedFilterOption): boolean | undefined {
    if (option === 'verified') {
        return true
    }
    if (option === 'unverified') {
        return false
    }
    return undefined
}
