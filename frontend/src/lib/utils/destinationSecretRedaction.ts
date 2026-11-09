import type { BeforeSendFn } from 'posthog-js'

const NETWORK_PLUGIN = 'rrweb/network@1'
const REDACTED = 'redacted'
const REDACTED_BODY = '[SessionRecording] body redacted as might contain a destination secret'
// The path of a Slack, Teams, Discord or generic webhook URL is the credential, and a PagerDuty routing key
// lets anyone open incidents. The SDK body scrubbing only matches words like "token" and "secret", so it misses both.
const SECRET_FIELD = /webhook[_-]?url|routing[_-]?key/i

function redactSecretFields(value: unknown): unknown {
    if (!value || typeof value !== 'object') {
        return value
    }
    if (Array.isArray(value)) {
        let copy: unknown[] | null = null
        value.forEach((item, index) => {
            const redacted = redactSecretFields(item)
            if (redacted !== item) {
                copy ??= [...value]
                copy[index] = redacted
            }
        })
        return copy ?? value
    }
    let copy: Record<string, unknown> | null = null
    for (const [key, item] of Object.entries(value)) {
        const redacted = SECRET_FIELD.test(key) && item !== null && item !== '' ? REDACTED : redactSecretFields(item)
        if (redacted !== item) {
            copy ??= { ...value }
            copy[key] = redacted
        }
    }
    return copy ?? value
}

export function redactDestinationSecrets(body: unknown): unknown {
    if (typeof body !== 'string' || !SECRET_FIELD.test(body)) {
        return body
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(body)
    } catch {
        return REDACTED_BODY
    }
    const redacted = redactSecretFields(parsed)
    return redacted === parsed ? body : JSON.stringify(redacted)
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
