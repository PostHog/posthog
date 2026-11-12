import type { Runtime } from '@/core/runtime'

// No imports, so the release scripts can use it without installing hog's dependencies. HOG_RELEASES_URL
// points it at another bucket, for tests and mirrors.
export const RELEASES_URL = 'https://releases.posthog.com/hog'
export const GITHUB_REPOSITORY = 'PostHog/posthog'

export function releasesUrl(runtime: Pick<Runtime, 'env'>): string {
    return (runtime.env.HOG_RELEASES_URL ?? RELEASES_URL).replace(/\/+$/, '')
}

export function manifestUrl(runtime: Pick<Runtime, 'env'>, version?: string): string {
    return version === undefined
        ? `${releasesUrl(runtime)}/stable/manifest.json`
        : `${releasesUrl(runtime)}/v${version.replace(/^v/, '')}/manifest.json`
}
