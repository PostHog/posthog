import type { BeforeSendFn, CaptureResult } from 'posthog-js'

const SEPARATOR = '(?:/|%2F)'
const UUID = '[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}'
const VALUE = `[^/?#&%\\s"'<>\\\\]+`
// The query of a reset link runs to its end in one greedy match, and a second pattern finds the token in it.
// Two passes keep the scan linear, whatever the length or number of the query parameters.
const RESET_QUERY = new RegExp(
    `${SEPARATOR}(?:reset|reset_2fa)${SEPARATOR}${UUID}${SEPARATOR}?(?:\\?|%3F)[^#\\s"'<>]*`,
    'gi'
)
const QUERY_TOKEN = new RegExp(`((?:\\?|&|%3F|%26)token(?:=|%3D))${VALUE}`, 'gi')
// Password reset, two-factor reset and email verification links carry a token after the user id.
// The id of an invite link is itself the secret: anyone who has it can accept the invite.
const SENSITIVE_SEGMENTS: [RegExp, string | ((match: string) => string)][] = [
    [
        new RegExp(`(${SEPARATOR}(?:reset|reset_2fa|verify_email)${SEPARATOR}${UUID}${SEPARATOR})${VALUE}`, 'gi'),
        '$1:token',
    ],
    [RESET_QUERY, (query) => query.replace(QUERY_TOKEN, '$1:token')],
    [new RegExp(`(${SEPARATOR}signup${SEPARATOR})${UUID}(?![0-9a-f])`, 'gi'), '$1:id'],
    // Invite signup passes the invite id to social login in the query.
    [new RegExp(`((?:\\?|&|%3F|%26)invite_id(?:=|%3D))${UUID}(?![0-9a-f])`, 'gi'), '$1:id'],
]
const MAY_HOLD_SECRET = /reset|verify_email|signup|invite_id/i
const NETWORK_PLUGIN = 'rrweb/network@1'
// The bodies of these requests hold invite ids without a URL around them.
const INVITE_REQUEST = new RegExp(`/api/(?:signup/${UUID}|organizations/[^/?#]+/invites)(?:[/?#]|$)`, 'i')
const REDACTED_BODY = '[SessionRecording] body redacted as might contain an invite'

/** Replaces the secret segment of a password reset, two-factor reset, email verification or invite URL
 * anywhere in the text, so the path stays useful for analysis. */
export function redactSensitiveUrl(text: string): string {
    if (!MAY_HOLD_SECRET.test(text)) {
        return text
    }
    return SENSITIVE_SEGMENTS.reduce(
        (redacted, [pattern, replacement]) =>
            typeof replacement === 'string'
                ? redacted.replace(pattern, replacement)
                : redacted.replace(pattern, replacement),
        text
    )
}

/** Replay compresses the page's DOM before `before_send` runs, so a link whose URL holds a secret is blocked
 * from replay instead. The class keeps click autocapture, and `redactSensitiveUrls` redacts its copy of the URL. */
export function replayBlockClassFor(url: string): string | undefined {
    return redactSensitiveUrl(url) === url ? undefined : 'ph-replay-block'
}

function redactArray(value: unknown[], seen: WeakMap<object, unknown>): unknown[] {
    let copy: unknown[] | null = null
    value.forEach((item, index) => {
        const redacted = redactValue(item, seen)
        if (redacted !== item) {
            copy ??= [...value]
            copy[index] = redacted
        }
    })
    return copy ?? value
}

/** Keys are redacted too, because heatmap data is keyed by URL. Two keys that redact to the same value
 * merge their arrays, so no heatmap point is lost. */
function redactObject(value: Record<string, unknown>, seen: WeakMap<object, unknown>): Record<string, unknown> {
    const original = Object.entries(value)
    const entries = original.map(([key, item]) => [redactSensitiveUrl(key), redactValue(item, seen)] as const)
    if (entries.every(([key, item], index) => key === original[index][0] && item === original[index][1])) {
        return value
    }
    const merged = new Map<string, unknown>()
    for (const [key, item] of entries) {
        const existing = merged.get(key)
        merged.set(key, Array.isArray(existing) && Array.isArray(item) ? [...existing, ...item] : item)
    }
    return Object.fromEntries(merged)
}

/** Every string at any depth, such as `$current_url`, `$session_entry_url`, an autocaptured `href`, or the
 * `href` of a replay meta event. A value with nothing to redact is returned as it is, so a large snapshot is not copied.
 * An object that appears more than once gets the same redacted copy each time. */
function redactValue(value: unknown, seen: WeakMap<object, unknown>): unknown {
    if (typeof value === 'string') {
        return redactSensitiveUrl(value)
    }
    if (!value || typeof value !== 'object') {
        return value
    }
    if (seen.has(value)) {
        return seen.get(value)
    }
    // Set before the recursion, so a cycle ends at the original object.
    seen.set(value, value)
    const redacted = Array.isArray(value)
        ? redactArray(value, seen)
        : redactObject(value as Record<string, unknown>, seen)
    seen.set(value, redacted)
    return redacted
}

function withoutInviteBodies(request: unknown): unknown {
    if (!request || typeof request !== 'object') {
        return request
    }
    const { name, requestBody, responseBody } = request as Record<string, unknown>
    if (typeof name !== 'string' || !INVITE_REQUEST.test(name)) {
        return request
    }
    return {
        ...request,
        ...(requestBody != null ? { requestBody: REDACTED_BODY } : {}),
        ...(responseBody != null ? { responseBody: REDACTED_BODY } : {}),
    }
}

function withoutInviteRequestBodies(snapshots: unknown): unknown {
    if (!Array.isArray(snapshots)) {
        return snapshots
    }
    let copy: unknown[] | null = null
    snapshots.forEach((snapshot, index) => {
        const data = snapshot?.data
        const requests = data?.plugin === NETWORK_PLUGIN ? data.payload?.requests : undefined
        if (!Array.isArray(requests)) {
            return
        }
        const redacted = requests.map(withoutInviteBodies)
        if (redacted.every((request, i) => request === requests[i])) {
            return
        }
        copy ??= [...snapshots]
        copy[index] = { ...snapshot, data: { ...data, payload: { ...data.payload, requests: redacted } } }
    })
    return copy ?? snapshots
}

function redactProperties(properties: CaptureResult['properties']): CaptureResult['properties'] {
    const snapshots = properties?.$snapshot_data
    const filtered = withoutInviteRequestBodies(snapshots)
    const base = filtered === snapshots ? properties : { ...properties, $snapshot_data: filtered }
    return redactValue(base, new WeakMap()) as CaptureResult['properties']
}

export const redactSensitiveUrls: BeforeSendFn = (event) => {
    const properties = redactProperties(event.properties)
    const $set = redactValue(event.$set, new WeakMap()) as CaptureResult['$set']
    const $set_once = redactValue(event.$set_once, new WeakMap()) as CaptureResult['$set_once']
    if (properties === event.properties && $set === event.$set && $set_once === event.$set_once) {
        return event
    }
    return { ...event, properties, $set, $set_once }
}
