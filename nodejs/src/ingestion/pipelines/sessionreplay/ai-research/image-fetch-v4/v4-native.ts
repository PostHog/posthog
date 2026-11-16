/**
 * The rules this lane shares with the recorder, reached through the v4 native addon rather than reimplemented here.
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
            typeof loaded.isUrlHistoryValue !== 'function' ||
            typeof loaded.parseV4UrlRef !== 'function' ||
            typeof loaded.sealFetchedImage !== 'function' ||
            typeof loaded.imageUrlHash !== 'function' ||
            typeof loaded.publicFontRefOf !== 'function' ||
            typeof loaded.publicUrlHash !== 'function'
        ) {
            throw new Error('the ai-research-v4-native addon is missing a shared rule: rebuild index.node')
        }
        cached = loaded
    }
    return cached
}

/** Runs a probe through each shared rule, so a stale `index.node` stops the pod at startup rather than in its first batch. */
export function assertSharedRulesLoaded(): void {
    const verdict = addon().tryCanonicalizeUrl('https://example.com/probe.png')
    if (!verdict.ok) {
        throw new Error(`the ai-research-v4-native addon refused a plain URL (${verdict.decline}): rebuild index.node`)
    }
    if (!runsSharedRules()) {
        throw new Error('the ai-research-v4-native addon failed a probe: rebuild index.node')
    }
}

const PROBE_REF = 'imageurl:v4:1:2026-01:AAAAAAAAAAAAAAAAAAAAAA'

function runsSharedRules(): boolean {
    const entry = JSON.stringify({ kind: 'url', key: 'probe', nextFetchAtMs: 1, storageExpiresAtMs: 1, outcome: 'ok' })
    const key = Buffer.alloc(32)
    try {
        // A stale index.node has no export, so the wrapper throws before it returns the promise.
        void addon()
            .sealFetchedImage(key, PROBE_REF, Buffer.alloc(0))
            .catch(() => undefined)
        return (
            addon().urlJob(1, undefined, 0) === 'drop' &&
            addon().isUrlHistoryValue('probe', entry) &&
            addon().parseV4UrlRef(PROBE_REF)?.hash === 'AAAAAAAAAAAAAAAAAAAAAA' &&
            addon().imageUrlHash(key, 'https://example.com/probe.png').length === 22 &&
            addon().publicUrlHash('https://example.com/probe.png').length === 22
        )
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

export type { V4UrlAsset, V4UrlRef } from '@posthog/ai-research-v4-native'

export function parseV4UrlRef(reference: string): import('@posthog/ai-research-v4-native').V4UrlRef | null {
    return addon().parseV4UrlRef(reference)
}

export function urlAssetOf(originalRef: string): import('@posthog/ai-research-v4-native').V4UrlAsset {
    return originalRef.startsWith('fonturl:') ? 'font' : 'image'
}

export function sealFetchedImage(teamMonthKey: Buffer, reference: string, image: Buffer): Promise<Buffer> {
    return addon().sealFetchedImage(teamMonthKey, reference, image)
}

export function imageUrlHash(teamMonthKey: Buffer, url: string): string {
    return addon().imageUrlHash(teamMonthKey, url)
}

export function publicFontRefOf(fetchUrl: string): string | null {
    return addon().publicFontRefOf(fetchUrl)
}

export function publicUrlHash(url: string): string {
    return addon().publicUrlHash(url)
}
