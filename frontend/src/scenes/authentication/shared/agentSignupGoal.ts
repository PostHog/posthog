import { getRelativeNextPath } from 'lib/utils/url'

// An agent that sends a person to sign up (the wizard, an MCP client) can name the goal it was given
// as a `goal` param on the `/oauth/authorize` URL it passes as `next`. The signup form puts it in the
// AI prompt follow-up. A social signup leaves for the identity provider and comes back on a page
// without `next`, so the goal is also kept in this tab's sessionStorage until a signup succeeds.
// The helpers use try/catch because sessionStorage can throw, for example in private windows.
const AGENT_SIGNUP_GOAL_KEY = 'ph_agent_signup_goal'
// Same limit as `referral_source_ai_prompt` on the signup serializers
const MAX_AGENT_SIGNUP_GOAL_LENGTH = 1000

function goalFromNext(location: Location): string | null {
    const nextPath = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)
    if (!nextPath) {
        return null
    }
    const url = new URL(nextPath, location.origin)
    if (url.pathname.replace(/\/$/, '') !== '/oauth/authorize') {
        return null
    }
    const goal = url.searchParams.get('goal')?.trim()
    return goal ? goal.slice(0, MAX_AGENT_SIGNUP_GOAL_LENGTH) : null
}

export function readAgentSignupGoal(location: Location = window.location): string | null {
    const goal = goalFromNext(location)
    try {
        if (goal) {
            sessionStorage.setItem(AGENT_SIGNUP_GOAL_KEY, goal)
            return goal
        }
        return sessionStorage.getItem(AGENT_SIGNUP_GOAL_KEY)
    } catch {
        return goal
    }
}

export function clearAgentSignupGoal(): void {
    try {
        sessionStorage.removeItem(AGENT_SIGNUP_GOAL_KEY)
    } catch {
        // Nothing to clear when storage is unavailable
    }
}
