import type { BeforeSendFn } from 'posthog-js'

const NETWORK_PLUGIN = 'rrweb/network@1'
const REDACTED = 'redacted'
const REDACTED_BODY = '[SessionRecording] body redacted as might contain a destination secret'
// The path of a Slack, Teams, Discord or generic webhook URL is the credential, and a PagerDuty routing key
// lets anyone open incidents. The SDK body scrubbing only matches words like "token" and "secret", so it misses both.
const SECRET_FIELD = /webhook[_-]?url|routing[_-]?key/i
// Only the webhook destination templates define a `url` input, so `inputs.url` of a destination is its webhook URL.
const MAY_HOLD_SECRET = /webhook[_-]?url|routing[_-]?key|"inputs"/i

function redactArray(value: unknown[]): unknown[] {
    const redacted = value.map(redactSecretFields)
    return redacted.some((item, index) => item !== value[index]) ? redacted : value
}

function redactUrlInput(inputs: unknown): unknown {
    if (!inputs || typeof inputs !== 'object' || Array.isArray(inputs)) {
        return inputs
    }
    const { url } = inputs as Record<string, unknown>
    return url === undefined || url === null ? inputs : { ...inputs, url: REDACTED }
}

function redactField(key: string, item: unknown): unknown {
    if (SECRET_FIELD.test(key) && item !== null && item !== '') {
        return REDACTED
    }
    const redacted = redactSecretFields(item)
    return key === 'inputs' ? redactUrlInput(redacted) : redacted
}

function redactObject(value: Record<string, unknown>): Record<string, unknown> {
    const entries = Object.entries(value).map(([key, item]) => [key, redactField(key, item)] as const)
    return entries.some(([key, item]) => item !== value[key]) ? Object.fromEntries(entries) : value
}

function redactSecretFields(value: unknown): unknown {
    if (!value || typeof value !== 'object') {
        return value
    }
    return Array.isArray(value) ? redactArray(value) : redactObject(value as Record<string, unknown>)
}

export function redactDestinationSecrets(body: unknown): unknown {
    if (typeof body !== 'string' || !MAY_HOLD_SECRET.test(body)) {
        return body
    }
    // A deeply nested body overflows the stack during traversal. The SDK drops the whole $snapshot event
    // when a before_send function throws, so every failure here redacts the body instead.
    try {
        const parsed = JSON.parse(body)
        const redacted = redactSecretFields(parsed)
        return redacted === parsed ? body : JSON.stringify(redacted)
    } catch {
        return REDACTED_BODY
    }
}

function redactRequest(request: unknown): unknown {
    if (!request || typeof request !== 'object') {
        return request
    }
    const { requestBody, responseBody } = request as Record<string, unknown>
    const redactedRequestBody = redactDestinationSecrets(requestBody)
    const redactedResponseBody = redactDestinationSecrets(responseBody)
    if (redactedRequestBody === requestBody && redactedResponseBody === responseBody) {
        return request
    }
    return { ...request, requestBody: redactedRequestBody, responseBody: redactedResponseBody }
}

function redactSnapshots(snapshots: unknown): unknown {
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
        const redacted = requests.map(redactRequest)
        if (redacted.every((request, i) => request === requests[i])) {
            return
        }
        copy ??= [...snapshots]
        copy[index] = { ...snapshot, data: { ...data, payload: { ...data.payload, requests: redacted } } }
    })
    return copy ?? snapshots
}

// A maskCapturedNetworkRequestFn would replace the SDK's body scrubbing, so this runs in before_send after it.
export const redactDestinationSecretsInReplay: BeforeSendFn = (event) => {
    const snapshots = event?.properties?.$snapshot_data
    const redacted = redactSnapshots(snapshots)
    return redacted === snapshots
        ? event
        : event && { ...event, properties: { ...event.properties, $snapshot_data: redacted } }
}
