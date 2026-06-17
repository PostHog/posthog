import { Counter } from 'prom-client'

import { Team } from '../../types'
import { parseJSON } from '../../utils/json-parse'

// A destination that fetches one of PostHog's own ingestion endpoints, authenticating
// as its own project, re-enters the event pipeline. If that re-ingested event then
// re-triggers the same destination, the chain forms an event-forwarding loop that
// doubles traffic on every hop.
//
// This is the observe-only stage: it detects the shape and emits a metric so we can
// measure real production traffic before designing enforcement. Modes are kept separate
// so a follow-up can add an enforcing mode without changing the detection surface.
export type SelfLoopGuardMode = 'disabled' | 'warn'

// Only these paths re-enter the event pipeline. Observability (`/i/v1/logs`) and the
// REST API (`/api/...`, `/decide`) do NOT re-trigger event processing, so a fetch to
// them - even with the project's own token - cannot form an event-forwarding loop.
const INGEST_PATHS = new Set(['/capture', '/batch', '/e', '/track', '/i/v0/e'])

// Top-level body fields that carry the credential a capture request authenticates with.
const API_KEY_FIELDS = ['api_key', 'token', 'api_token'] as const

export const selfLoopGuardCounter = new Counter({
    name: 'cdp_self_loop_guard_total',
    help: 'Count of fetches the self-loop guard detected as self-referential, by mode',
    labelNames: ['mode', 'action'],
})

export const isPostHogIngestUrl = (urlString: string): boolean => {
    try {
        const url = new URL(urlString)
        const host = url.hostname.toLowerCase()
        if (host !== 'posthog.com' && !host.endsWith('.posthog.com')) {
            return false
        }
        const path = url.pathname.replace(/\/+$/, '') || '/'
        return INGEST_PATHS.has(path)
    } catch {
        return false
    }
}

// The credential a capture request authenticates with - either a top-level body field
// or an `api_key`/`token` query parameter. Deliberately does NOT look at `$lib_token`
// (SDK metadata auto-attached to event properties) or `Authorization` headers, both of
// which carry a token without expressing intent to ingest as that project.
export const extractRequestApiKey = (body: string | null | undefined, urlString: string): string | null => {
    if (body) {
        try {
            const parsed = parseJSON(body)
            if (parsed && typeof parsed === 'object') {
                const obj = parsed as Record<string, unknown>
                for (const field of API_KEY_FIELDS) {
                    if (typeof obj[field] === 'string') {
                        return obj[field] as string
                    }
                }
            }
        } catch {
            // Not JSON - fall through to the query string.
        }
    }
    try {
        const params = new URL(urlString).searchParams
        return params.get('api_key') ?? params.get('token')
    } catch {
        return null
    }
}

const ownsToken = (team: Pick<Team, 'api_token' | 'secret_api_token'>, token: string): boolean => {
    return token === team.api_token || (team.secret_api_token !== null && token === team.secret_api_token)
}

// True when a fetch targets a PostHog ingestion endpoint authenticating with the
// invocation's own project token - i.e. the shape that can form an event-forwarding
// loop. Returns false for cross-project replication (a different project's token),
// non-ingest endpoints, and requests carrying no project credential.
export const isSelfReferentialIngestFetch = (input: {
    url: string
    body: string | null | undefined
    team: Pick<Team, 'api_token' | 'secret_api_token'>
}): boolean => {
    if (!isPostHogIngestUrl(input.url)) {
        return false
    }
    const requestToken = extractRequestApiKey(input.body, input.url)
    return requestToken !== null && ownsToken(input.team, requestToken)
}
