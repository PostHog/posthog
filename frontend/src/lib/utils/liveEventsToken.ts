import { teamLogic } from 'scenes/teamLogic'

let refreshInFlight: Promise<string | null> | null = null

/**
 * Refetch the team to replace a rejected `live_events_token`.
 *
 * The token is a 7-day JWT that arrives with the team, so a tab that stays open longer than
 * that keeps sending an expired bearer to the livestream. The server caches each token for 24h,
 * so a refetch always answers with one that has at least 6 days left.
 *
 * Pass the token that was rejected. Every stream on the page holds the same one, so a caller
 * whose token has already moved on reads the new one instead of asking again, and concurrent
 * callers share one refetch.
 */
export function refreshLiveEventsToken(staleToken: string | undefined): Promise<string | null> {
    const logic = teamLogic.findMounted()
    if (!logic) {
        return Promise.resolve(null)
    }
    const readToken = (): string | null => logic.values.currentTeam?.live_events_token ?? null
    if (staleToken && readToken() !== staleToken) {
        return Promise.resolve(readToken())
    }
    // `refreshCurrentTeam` rather than `loadCurrentTeam`: it drops a response for a team the user
    // has since switched away from, and it does not fire the team-load action that other logics
    // use to reload themselves.
    refreshInFlight ??= logic.asyncActions
        .refreshCurrentTeam()
        .then(readToken)
        .finally(() => {
            refreshInFlight = null
        })
    return refreshInFlight
}
