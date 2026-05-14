import { z } from 'zod'

/** Resolved application + live revision payload returned by Django. */
export const ResolvedRevisionSchema = z.object({
    applicationId: z.string().uuid(),
    applicationSlug: z.string(),
    teamId: z.number().int(),
    revisionId: z.string().uuid(),
    revisionState: z.enum(['pending_upload', 'uploaded', 'validating', 'ready', 'failed']),
    bundleS3Key: z.string(),
    bundleSha256: z.string(),
    topLevelConfig: z.record(z.string(), z.unknown()),
    parsedManifest: z.record(z.string(), z.unknown()).nullable(),
    auth: z.discriminatedUnion('mode', [
        z.object({ mode: z.literal('public') }),
        z.object({ mode: z.literal('shared_secret'), token: z.string().min(1) }),
        z.object({ mode: z.literal('webhook_signature'), provider: z.string(), secret: z.string().min(1) }),
    ]),
})

export type ResolvedRevision = z.infer<typeof ResolvedRevisionSchema>

export const SecretsResponseSchema = z.object({
    secrets: z.record(z.string(), z.string()),
})

export type SecretsResponse = z.infer<typeof SecretsResponseSchema>
