import { z } from 'zod'

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
