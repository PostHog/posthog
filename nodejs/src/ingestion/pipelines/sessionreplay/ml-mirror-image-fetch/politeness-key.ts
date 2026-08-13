/**
 * The registrable domain of a host, from the same function the collector keys the topic with.
 *
 * One public suffix list answers for the producer and for this lane, so the key a record arrives
 * under and the key its budget is scoped to cannot drift.
 *
 * The addon holds a 15 MB native library, and `index.ts` imports every server whatever mode the pod
 * runs. It is loaded on first use rather than at import, so only a pod in this lane pays for it. The
 * mirror server defers it the same way.
 */
let cached: ((host: string) => string) | undefined

export function politenessKey(host: string): string {
    if (!cached) {
        const addon = require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
        if (typeof addon.politenessKey !== 'function') {
            throw new Error('the replay-anonymizer addon has no politenessKey: rebuild index.node')
        }
        cached = addon.politenessKey
    }
    return cached(host)
}
