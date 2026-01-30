import { z } from 'zod'

import { ValidRetentionPeriods } from '../session-recording/constants'

// Schema for positive integer string (e.g., "123" -> 123)
const positiveIntString = (fieldName: string) =>
    z
        .string({ required_error: `Missing ${fieldName} parameter` })
        .regex(/^\d+$/, `Invalid ${fieldName} parameter`)
        .transform(Number)
        .pipe(z.number().positive(`Invalid ${fieldName} parameter`))

// Schema for non-negative integer string (e.g., "0" -> 0, "123" -> 123)
const nonNegativeIntString = (fieldName: string) =>
    z
        .string({ required_error: `Missing ${fieldName} query parameter` })
        .regex(/^\d+$/, `Invalid ${fieldName} query parameter`)
        .transform(Number)
        .pipe(z.number().nonnegative())

// Shared schema for recording path params
export const RecordingParamsSchema = z.object({
    team_id: positiveIntString('team_id'),
    session_id: z.string({ required_error: 'Missing session_id parameter' }).min(1, 'Invalid session_id parameter'),
})

// Creates a schema for getBlock query params with S3 key validation using the configured prefix
export function createGetBlockQuerySchema(s3Prefix: string) {
    // Key format: {prefix}/{retention_period}/{timestamp}-{hex_suffix}
    // Example: session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee
    const s3KeyRegex = new RegExp(`^${s3Prefix}/(${ValidRetentionPeriods.join('|')})/\\d+-[0-9a-f]{16}$`)

    return z
        .object({
            key: z
                .string({ required_error: 'Missing key query parameter' })
                .min(1, 'Invalid key query parameter')
                .regex(s3KeyRegex, {
                    message: `Invalid key format: must match ${s3Prefix}/{${ValidRetentionPeriods.join(',')}}/{timestamp}-{hex}`,
                }),
            start: nonNegativeIntString('start'),
            end: nonNegativeIntString('end'),
        })
        .refine((data) => data.start <= data.end, {
            message: 'start must be less than or equal to end',
            path: ['start'],
        })
}
