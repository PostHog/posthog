import { getRelativeNextPath } from 'lib/utils/url'

// An agent that sends a person to sign up (the wizard, an MCP client) can name the goal it was given
// as a `goal` param on the `/oauth/authorize` URL it passes as `next`. The signup form puts it in the
// AI prompt follow-up. A social signup leaves for the identity provider and comes back on a page
// without `next`, so the goal is also kept in this tab's sessionStorage until a signup succeeds.
// A page with a `next` belongs to the attempt that URL names, so its goal (or lack of one) replaces
// the cache — an abandoned attempt's goal must not leak into a later, unrelated signup in this tab.
// The helpers use try/catch because sessionStorage can throw, for example in private windows.
const AGENT_SIGNUP_GOAL_KEY = 'ph_agent_signup_goal'
// Same limit as `referral_source_ai_prompt` on the signup serializers
const MAX_AGENT_SIGNUP_GOAL_LENGTH = 1000

function goalFromNextPath(nextPath: string, location: Location): string | null {
    const url = new URL(nextPath, location.origin)
    if (url.pathname.replace(/\/$/, '') !== '/oauth/authorize') {
        return null
    }
    const goal = url.searchParams.get('goal')?.trim()
    return goal ? goal.slice(0, MAX_AGENT_SIGNUP_GOAL_LENGTH) : null
}

export function readAgentSignupGoal(location: Location = window.location): string | null {
    const nextPath = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)
    if (!nextPath) {
        try {
            return sessionStorage.getItem(AGENT_SIGNUP_GOAL_KEY)
        } catch {
            return null
        }
    }
    const goal = goalFromNextPath(nextPath, location)
    try {
        if (goal) {
            sessionStorage.setItem(AGENT_SIGNUP_GOAL_KEY, goal)
        } else {
            sessionStorage.removeItem(AGENT_SIGNUP_GOAL_KEY)
        }
    } catch {
        // Storage unavailable; the goal read from the URL still applies to this page
    }
    return goal
}

export function clearAgentSignupGoal(): void {
    try {
        sessionStorage.removeItem(AGENT_SIGNUP_GOAL_KEY)
    } catch {
        // Nothing to clear when storage is unavailable
    }
}
