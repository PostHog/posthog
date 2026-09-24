import { teamLogic } from 'scenes/teamLogic'

let refreshInFlight: Promise<string | null> | null = null

/** A livestream stream was refused because its bearer token was rejected. */
export function isLivestreamUnauthorized(error: unknown): boolean {
    return typeof error === 'object' && error !== null && (error as { status?: number }).status === 401
}

/**
 * Refetch the team to replace a rejected `live_events_token`.
 *
 * The token is a 7-day JWT that arrives with the team, so a tab that stays open longer than
 * that keeps sending an expired bearer to the livestream. The server caches each token for 24h,
 * so a refetch always answers with one that has at least 6 days left.
 *
 * Concurrent callers share one refetch, because several streams hold the same token and all of
 * them see the 401 at the same time.
 */
export function refreshLiveEventsToken(): Promise<string | null> {
    if (!refreshInFlight) {
        const logic = teamLogic.findMounted()
        if (!logic) {
            return Promise.resolve(null)
        }
        refreshInFlight = logic.asyncActions
            .loadCurrentTeam()
            .then(() => logic.values.currentTeam?.live_events_token ?? null)
            .catch(() => null)
            .finally(() => {
                refreshInFlight = null
            })
    }
    return refreshInFlight
}
