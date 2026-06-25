/**
 * Caller-supplied `client_kind` tag stamped on a session at /run time.
 *
 * Purely a UX hint — NOT a security boundary. The header is unauthenticated
 * (forgeable under `shared_secret`); the runner only uses it to suppress
 * surfaces that don't make sense for a given client (e.g. the
 * "approve it here: <url>" prose for posthog-code, whose chat preview
 * already renders an in-line approval card).
 *
 * Storage: lives in `trigger_metadata.client_kind` on `agent_session`, set
 * once at session creation and never rewritten.
 */

/** Canonical header name (case-insensitive at the HTTP layer). */
export const CLIENT_KIND_HEADER = 'x-posthog-client'

/** PostHog Code desktop app — the chat preview renders approvals in-line. */
export const CLIENT_KIND_POSTHOG_CODE = 'posthog-code'

/** Allowlist of recognised client_kind values. Unknown values are dropped. */
export const KNOWN_CLIENT_KINDS = [CLIENT_KIND_POSTHOG_CODE] as const

export type ClientKind = (typeof KNOWN_CLIENT_KINDS)[number]

/**
 * Normalise a raw header value into a recognised `ClientKind`, or `null`.
 * Forward-compat: unknown values are dropped silently rather than throwing —
 * an old runner seeing a new client_kind from a newer ingress shouldn't crash.
 */
export function parseClientKind(raw: string | string[] | undefined | null): ClientKind | null {
    if (raw === undefined || raw === null) {
        return null
    }
    const value = Array.isArray(raw) ? raw[0] : raw
    if (typeof value !== 'string') {
        return null
    }
    const trimmed = value.trim().toLowerCase()
    return (KNOWN_CLIENT_KINDS as readonly string[]).includes(trimmed) ? (trimmed as ClientKind) : null
}

/**
 * Read `client_kind` off a session row's `trigger_metadata`. Same forward-compat
 * shape as `parseClientKind` — unknown / missing → `null`.
 */
export function readSessionClientKind(triggerMetadata: Record<string, unknown> | null | undefined): ClientKind | null {
    if (!triggerMetadata) {
        return null
    }
    const raw = triggerMetadata.client_kind
    return typeof raw === 'string' ? parseClientKind(raw) : null
}
