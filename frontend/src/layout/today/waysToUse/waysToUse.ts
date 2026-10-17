import type { UserType } from '~/types'

export const WAYS_TO_USE_SEEN_KEY = 'today-ways-to-use'

export const WAYS_TO_USE_PARAM = 'ways_to_use'

const NEWCOMER_WINDOW_MS = 14 * 24 * 60 * 60 * 1000

export type WaysToUseSurface = 'chat' | 'slack' | 'mcp'

export type WaysToUseCloseSource = 'get_started' | 'dismiss' | 'surface_link'

export interface WaysToUseEligibility {
    todayRailEnabled: boolean
    onHome: boolean
    user: UserType | null
    welcomeDialogDue: boolean
    now: number
}

function isNewcomer(user: UserType, now: number): boolean {
    const joinedAt = Date.parse(user.date_joined)
    return !Number.isNaN(joinedAt) && now - joinedAt < NEWCOMER_WINDOW_MS
}

export function shouldOfferWaysToUse({
    todayRailEnabled,
    onHome,
    user,
    welcomeDialogDue,
    now,
}: WaysToUseEligibility): boolean {
    if (!todayRailEnabled || !onHome || !user || welcomeDialogDue) {
        return false
    }
    return !user.has_seen_product_intro_for?.[WAYS_TO_USE_SEEN_KEY] && isNewcomer(user, now)
}
