/**
 * The URL policy of the collector, reached through the node addon rather than reimplemented here. One
 * public suffix list answers for the producer and for this lane, so the key a record arrives under
 * and the key its budget is scoped to cannot drift.
 *
 * The addon holds a 15 MB native library, and `index.ts` imports every server whatever mode the pod
 * runs. This loads the addon on first use rather than at import, so only a pod in this lane pays for
 * it. The mirror server defers it the same way.
 */
let cached: typeof import('@posthog/replay-anonymizer') | undefined

function addon(): typeof import('@posthog/replay-anonymizer') {
    if (!cached) {
        const loaded = require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
        if (typeof loaded.politenessKey !== 'function' || typeof loaded.isPublicHost !== 'function') {
            throw new Error('the replay-anonymizer addon is missing the url policy: rebuild index.node')
        }
        cached = loaded
    }
    return cached
}

export function politenessKey(host: string): string {
    return addon().politenessKey(host)
}

/**
 * False for a host the collector would have declined: a private or reserved address, and a name
 * that only resolves inside a network.
 *
 * The connection layer refuses a private address, so this is not the only guard against one. It is
 * the only guard against a name that looks internal and whose DNS answer is public, because no
 * address check can refuse that. Requirement 35.
 */
export function isPublicHost(host: string): boolean {
    return addon().isPublicHost(host)
}
