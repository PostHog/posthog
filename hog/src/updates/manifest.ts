import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseJson } from '@/core/json'
import type { Runtime } from '@/core/runtime'

import { manifestUrl } from './release-urls'
import { parseVersion } from './version'

const VersionText = z.string().refine((text) => parseVersion(text) !== undefined, { error: 'Not a semver version' })

export const ArtifactSchema = z.object({
    file: z.string().regex(/^[\w.-]+$/),
    sha256: z.string().regex(/^[0-9a-f]{64}$/),
    size: z.number().int().nonnegative(),
})

export const ManifestSchema = z.object({
    schema: z.literal(1),
    name: z.literal('hog'),
    version: VersionText,
    tag: z.string(),
    prerelease: z.boolean(),
    publishedAt: z.iso.datetime({ offset: true }),
    buildDate: z.iso.datetime({ offset: true }),
    // Releases below it have a problem bad enough that every command warns about it.
    minimumVersion: VersionText.optional(),
    baseUrl: z.url(),
    mirrorUrl: z.url(),
    artifacts: z.record(z.string(), ArtifactSchema),
})

export type Artifact = z.infer<typeof ArtifactSchema>
export type Manifest = z.infer<typeof ManifestSchema>

export async function fetchManifest(
    runtime: Pick<Runtime, 'env' | 'fetch'>,
    options: { version?: string; timeoutMs?: number } = {}
): Promise<Manifest> {
    const url = manifestUrl(runtime, options.version)
    let response: Response
    try {
        response = await runtime.fetch(url, { timeoutMs: options.timeoutMs ?? 10_000, skipRateLimit: true })
    } catch {
        throw new HogError(
            'release_unreachable',
            `hog couldn't reach ${url}.`,
            'Check your connection and run the command again.'
        )
    }

    if (response.status === 404 && options.version !== undefined) {
        throw new HogError(
            'unknown_version',
            `There is no hog ${options.version}.`,
            'Run `hog upgrade` without --version for the latest release.'
        )
    }
    if (!response.ok) {
        throw new HogError(
            'release_unreachable',
            `${url} answered with HTTP ${response.status}.`,
            'Run the command again in a few minutes.'
        )
    }

    return parseJson(await response.text(), ManifestSchema, {
        code: 'invalid_release_manifest',
        hint: 'The release manifest is broken. Run the command again in a few minutes.',
    })
}
