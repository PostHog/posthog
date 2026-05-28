import { z } from 'zod'

import { widgetDateRangeSchema } from './widgetDateRangeOptions'

/** Shared widget config fields inherited by all widget types. */
export const baseWidgetConfigSchema = z.object({
    filterTestAccounts: z.boolean().optional(),
})

export type BaseWidgetConfig = z.infer<typeof baseWidgetConfigSchema>

export function resolveWidgetFilterTestAccounts(
    configValue: boolean | undefined | null,
    projectDefault: boolean
): boolean {
    return configValue ?? projectDefault
}

// New widget types: add per-type schemas here — CONTRIBUTING.md
const limitFieldSchema = z
    .number({ invalid_type_error: 'Must be an integer between 1 and 25.' })
    .int('Must be an integer between 1 and 25.')
    .min(1, 'Must be an integer between 1 and 25.')
    .max(25, 'Must be an integer between 1 and 25.')

export const errorTrackingWidgetConfigSchema = baseWidgetConfigSchema.extend({
    limit: limitFieldSchema.default(25),
    orderBy: z.enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions']).default('occurrences'),
    orderDirection: z.enum(['ASC', 'DESC']).default('DESC'),
    status: z.enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all']).default('active'),
    dateRange: widgetDateRangeSchema,
})

export type ErrorTrackingWidgetConfig = z.infer<typeof errorTrackingWidgetConfigSchema>

export const sessionReplayWidgetConfigSchema = baseWidgetConfigSchema.extend({
    limit: limitFieldSchema.default(10),
    orderBy: z
        .enum(['start_time', 'activity_score', 'recording_duration', 'duration', 'click_count', 'console_error_count'])
        .default('start_time'),
    orderDirection: z.enum(['ASC', 'DESC']).default('DESC'),
    dateRange: widgetDateRangeSchema,
})

export type SessionReplayWidgetConfig = z.infer<typeof sessionReplayWidgetConfigSchema>
