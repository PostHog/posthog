import { Counter } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'

import { Team } from '../../types'

// A destination that fetches one of PostHog's own ingestion endpoints, authenticating
// as its own project, re-enters the event pipeline. If that re-ingested event then
// re-triggers the same destination, the chain forms an event-forwarding loop that
// doubles traffic on every hop. The guard bounds the loop by counting how many times
// *this specific destination* has re-fed the pipeline - allowing the first
// SELF_LOOP_MAX_DEPTH hops, then breaking it.

// Event property carrying the self-loop depth *per hog function*, keyed by function id:
//   { "<functionId>": <hops this destination has re-fed itself> }
// Keying by function id is deliberate: a destination is bounded only by its OWN re-entries,
// so an event that merely passed through many unrelated functions can never trip the guard
// for a legitimately-running destination. Distinct from the shared
// `$hog_function_execution_count` that bounds the `postHogCapture` path.
export const SELF_LOOP_DEPTH_PROPERTY = '$hog_function_self_loop_depth'

// Max self-capture hops, for a single destination, before its loop is broken.
export const SELF_LOOP_MAX_DEPTH = 10

// Only these paths re-enter the event pipeline. Observability (`/i/v1/logs`) and the
// REST API (`/api/...`, `/decide`) do NOT re-trigger event processing, so a fetch to
// them - even with the project's own token - cannot form an event-forwarding loop.
const INGEST_PATHS = new Set(['/capture', '/batch', '/e', '/track', '/i/v0/e'])

// Top-level body fields that carry the credential a capture request authenticates with.
const API_KEY_FIELDS = ['api_key', 'token', 'api_token'] as const

export const selfLoopGuardCounter = new Counter({
    name: 'cdp_self_loop_guard_total',
    help: 'Count of fetches the self-loop guard acted on, by mode and action',
    labelNames: ['mode', 'action'],
})

export const isPostHogIngestUrl = (urlString: string): boolean => {
    try {
        const url = new URL(urlString)
        const host = url.hostname.toLowerCase()
        const isIngestHost = host === 'posthog.com' || host.endsWith('.posthog.com')
        if (!isIngestHost) {
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

// How many times the given hog function has already re-fed the pipeline on this chain,
// read from the per-function depth map. Returns 0 when absent or malformed.
//
// The depth rides on event properties a project owner can set, so it is untrusted: clamp
// to a non-negative integer. Without this, a seeded negative value (e.g. -999) would read
// straight through and delay the cap by ~1000 hops; non-finite values are ignored too.
export const getSelfLoopDepth = (
    properties: Record<string, unknown> | null | undefined,
    functionId: string
): number => {
    const map = properties?.[SELF_LOOP_DEPTH_PROPERTY]
    if (map && typeof map === 'object' && !Array.isArray(map)) {
        const depth = (map as Record<string, unknown>)[functionId]
        if (typeof depth === 'number' && Number.isFinite(depth)) {
            return Math.max(0, Math.floor(depth))
        }
    }
    return 0
}

// Stamp the given function's incremented self-loop depth onto the outgoing capture body so
// the re-ingested event carries it forward. Only this function's entry is touched - other
// functions' depths in the map are preserved. Handles single-event and batch shapes.
// Returns the body unchanged if it can't be parsed as a capture payload.
export const injectSelfLoopDepth = (
    body: string | null | undefined,
    functionId: string,
    depth: number
): string | null | undefined => {
    if (!body) {
        return body
    }
    let parsed: unknown
    try {
        parsed = parseJSON(body)
    } catch {
        return body
    }
    if (!parsed || typeof parsed !== 'object') {
        return body
    }
    const stamp = (event: Record<string, unknown>): void => {
        const properties = (event.properties && typeof event.properties === 'object' ? event.properties : {}) as Record<
            string,
            unknown
        >
        // Reject an array here: it passes `typeof === 'object'` but `JSON.stringify` drops the
        // non-index `functionId` property, so a seeded array would silently lose the depth and
        // let the loop run uncapped. Start fresh instead.
        const existing = properties[SELF_LOOP_DEPTH_PROPERTY]
        const depthMap = (
            existing && typeof existing === 'object' && !Array.isArray(existing) ? existing : {}
        ) as Record<string, unknown>
        depthMap[functionId] = depth
        properties[SELF_LOOP_DEPTH_PROPERTY] = depthMap
        event.properties = properties
    }
    const obj = parsed as Record<string, unknown>
    if (Array.isArray(obj.batch)) {
        for (const entry of obj.batch) {
            if (entry && typeof entry === 'object') {
                stamp(entry as Record<string, unknown>)
            }
        }
    } else {
        stamp(obj)
    }
    return JSON.stringify(parsed)
}
