import type { BeforeSendFn } from 'posthog-js'

const NETWORK_PLUGIN = 'rrweb/network@1'

function redactSnapshots(snapshots: unknown, redactRequest: (request: unknown) => unknown): unknown {
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

/** Runs `redactRequest` on every network request in a replay snapshot. Return the same request to leave it alone. */
export function redactReplayRequests(redactRequest: (request: unknown) => unknown): BeforeSendFn {
    return (event) => {
        const snapshots = event?.properties?.$snapshot_data
        const redacted = redactSnapshots(snapshots, redactRequest)
        return redacted === snapshots
            ? event
            : event && { ...event, properties: { ...event.properties, $snapshot_data: redacted } }
    }
}
