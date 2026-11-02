/**
 * The URL policy and the crawl history rule of the recorder, reached through the v4 native addon
 * rather than reimplemented here. One public suffix list keeps producer and consumer
 * canonicalization aligned.
 *
 * The addon is a native library, and `index.ts` imports every server whatever mode the pod runs.
 * This loads the addon on first use rather than at import, so only a pod in this lane pays for it.
 * The fetch server defers it the same way.
 */
let cached: typeof import('@posthog/ai-research-v4-native') | undefined

function addon(): typeof import('@posthog/ai-research-v4-native') {
    if (!cached) {
        const loaded = require('@posthog/ai-research-v4-native') as typeof import('@posthog/ai-research-v4-native')
        if (
            typeof loaded.politenessKey !== 'function' ||
            typeof loaded.isPublicHost !== 'function' ||
            typeof loaded.tryCanonicalizeUrl !== 'function' ||
            typeof loaded.urlJob !== 'function' ||
            typeof loaded.isUrlHistoryValue !== 'function'
        ) {
            throw new Error('the ai-research-v4-native addon is missing a shared rule: rebuild index.node')
        }
        cached = loaded
    }
    return cached
}

/**
 * Load the addon now and run one URL and one crawl history entry through it, so a stale `index.node` stops the pod at
 * startup.
 *
 * The parser calls into it for every URL, and the crawl history reader for every URL row. A stale addon must stop the
 * pod before it reads a batch.
 */
export function assertUrlPolicyLoaded(): void {
    const verdict = addon().tryCanonicalizeUrl('https://example.com/probe.png')
    if (!verdict.ok) {
        throw new Error(`the ai-research-v4-native addon refused a plain URL (${verdict.decline}): rebuild index.node`)
    }
    if (!readsCrawlHistory()) {
        throw new Error('the ai-research-v4-native addon misread a crawl history entry: rebuild index.node')
    }
}

function readsCrawlHistory(): boolean {
    const entry = JSON.stringify({ kind: 'url', key: 'probe', nextFetchAtMs: 1, storageExpiresAtMs: 1, outcome: 'ok' })
    try {
        return addon().urlJob(1, undefined, 0) === 'drop' && addon().isUrlHistoryValue('probe', entry)
    } catch {
        return false
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

export function canonicalizeUrl(url: string): import('@posthog/ai-research-v4-native').CanonicalUrl | null {
    return addon().canonicalizeUrl(url)
}

export function tryCanonicalizeUrl(url: string): import('@posthog/ai-research-v4-native').UrlPolicyVerdict {
    return addon().tryCanonicalizeUrl(url)
}

export function urlJob(
    nextFetchAtMs: number,
    storedAtMs: number | undefined,
    nowMs: number
): import('@posthog/ai-research-v4-native').UrlJob {
    return addon().urlJob(nextFetchAtMs, storedAtMs, nowMs)
}

export function isUrlHistoryValue(key: string, value: string): boolean {
    return addon().isUrlHistoryValue(key, value)
}
