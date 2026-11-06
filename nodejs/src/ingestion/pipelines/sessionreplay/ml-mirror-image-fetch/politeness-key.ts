/**
 * The URL policy of the collector, reached through the node addon rather than reimplemented here.
 * One public suffix list keeps producer and consumer canonicalization aligned.
 *
 * The addon holds a 15 MB native library, and `index.ts` imports every server whatever mode the pod
 * runs. This loads the addon on first use rather than at import, so only a pod in this lane pays for
 * it. The mirror server defers it the same way.
 */
let cached: typeof import('@posthog/replay-anonymizer') | undefined

function addon(): typeof import('@posthog/replay-anonymizer') {
    if (!cached) {
        const loaded = require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
        if (
            typeof loaded.politenessKey !== 'function' ||
            typeof loaded.isPublicHost !== 'function' ||
            typeof loaded.tryCanonicalizeUrl !== 'function'
        ) {
            throw new Error('the replay-anonymizer addon is missing the url policy: rebuild index.node')
        }
        cached = loaded
    }
    return cached
}

/**
 * Load the addon now and run one URL through it, so a stale `index.node` stops the pod at startup.
 *
 * The parser calls into it for every URL. A stale addon must stop the pod before it reads a batch.
 */
export function assertUrlPolicyLoaded(): void {
    const verdict = addon().tryCanonicalizeUrl('https://example.com/probe.png')
    if (!verdict.ok) {
        throw new Error(`the replay-anonymizer addon refused a plain URL (${verdict.decline}): rebuild index.node`)
    }
}

export function politenessKey(host: string): string {
    return addon().politenessKey(host)
}

/**
 * False for a host the collector would decline, including private and reserved names.
 *
 * The connection layer refuses a private address, so this is not the only guard against one. It is
 * the only guard against a name that looks internal and whose DNS answer is public, because no
 * address check can refuse that.
 */
export function isPublicHost(host: string): boolean {
    return addon().isPublicHost(host)
}

export function canonicalizeUrl(url: string): import('@posthog/replay-anonymizer').CanonicalUrl | null {
    return addon().canonicalizeUrl(url)
}

export function tryCanonicalizeUrl(url: string): import('@posthog/replay-anonymizer').UrlPolicyVerdict {
    return addon().tryCanonicalizeUrl(url)
}
