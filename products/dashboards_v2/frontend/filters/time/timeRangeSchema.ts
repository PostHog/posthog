import { z } from 'zod'

// The query batch endpoint's limit. A longer end fails the whole batch, and with it every other tile's query.
const MAX_TIME_END = 100

export const RELATIVE_TIME = /^now-(\d+)([smhdwMy])$/

const timePointSchema = z
    .string()
    .max(MAX_TIME_END)
    .refine(
        (point) => point === 'now' || RELATIVE_TIME.test(point) || !Number.isNaN(Date.parse(point)),
        'Use now, now-<amount><s|m|h|d|w|M|y>, or an ISO 8601 time'
    )

/**
 * The time range a query runs over. Each end is an expression such as `now-7d` or `now`, or an ISO 8601 time. Keep
 * relative ends relative, because the backend then caches the result under the same key on every reload.
 */
export const timeRangeSchema = z.object({ from: timePointSchema, to: timePointSchema })

export type TimeRange = z.infer<typeof timeRangeSchema>
