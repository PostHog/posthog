import type { Runtime } from '@/core/runtime'

// Each release uploads its files under hog/v<version>/, which never change, then rewrites
// hog/stable/manifest.json, which points at the latest release. HOG_RELEASES_URL moves both, for tests
// and mirrors. install.sh and install.ps1 read the same files. This module imports nothing, so the
// release scripts can use it without installing hog's dependencies.
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
