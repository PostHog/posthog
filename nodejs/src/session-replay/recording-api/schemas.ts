import { z } from 'zod'

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

// Static schema for getBlock query params (validates structure only)
export const GetBlockQuerySchema = z
    .object({
        key: z.string({ required_error: 'Missing key query parameter' }).min(1, 'Invalid key query parameter'),
        start: nonNegativeIntString('start'),
        end: nonNegativeIntString('end'),
    })
    .refine((data) => data.start <= data.end, {
        message: 'start must be less than or equal to end',
        path: ['start'],
    })
