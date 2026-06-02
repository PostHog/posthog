import { z } from 'zod'

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

/** Relative `date_from` values allowed on dashboard widget configs (shortest first). */
export const WIDGET_DATE_FROM_VALUES = ['-1h', '-3h', '-24h', '-7d', '-14d', '-30d', '-90d'] as const

export type WidgetDateFromValue = (typeof WIDGET_DATE_FROM_VALUES)[number]

export const widgetDateFromSchema = z.enum(WIDGET_DATE_FROM_VALUES, {
    message: 'Select a supported date range.',
})

export const WIDGET_DATE_RANGE_SELECT_OPTIONS: { value: WidgetDateFromValue; label: string }[] = [
    { value: '-1h', label: 'Last hour' },
    { value: '-3h', label: 'Last 3 hours' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-14d', label: 'Last 14 days' },
    { value: '-30d', label: 'Last 30 days' },
    { value: '-90d', label: 'Last 90 days' },
]

const widgetDateRangeObjectSchema = z
    .object({
        date_from: widgetDateFromSchema.optional(),
        date_to: z.string().optional(),
        explicitDate: z.boolean().optional(),
    })
    .superRefine((value, ctx) => {
        const hasDateFrom = value.date_from !== undefined
        const hasDateTo = value.date_to !== undefined && value.date_to !== ''
        const hasExplicitDate = value.explicitDate === true

        if (!hasDateFrom && !hasDateTo && !hasExplicitDate) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: 'Select a date range or enable explicit dates.',
            })
        }
    })

export const widgetDateRangeSchema = widgetDateRangeObjectSchema.optional()

/** Shared limit field for list-style dashboard widgets (1–25 rows). */
export const widgetLimitFieldSchema = z
    .number({ error: 'Must be an integer between 1 and 25.' })
    .int('Must be an integer between 1 and 25.')
    .min(1, 'Must be an integer between 1 and 25.')
    .max(25, 'Must be an integer between 1 and 25.')

export const widgetOrderDirectionSchema = z.enum(['ASC', 'DESC']).default('DESC')

// New widget types: add per-type schemas here — CONTRIBUTING.md
export const errorTrackingWidgetConfigSchema = baseWidgetConfigSchema.extend({
    limit: widgetLimitFieldSchema.default(10),
    orderBy: z.enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions']).default('occurrences'),
    orderDirection: widgetOrderDirectionSchema,
    status: z.enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all']).default('active'),
    dateRange: widgetDateRangeSchema,
})

export type ErrorTrackingWidgetConfig = z.infer<typeof errorTrackingWidgetConfigSchema>

/** Form fields edited in the error tracking widget settings modal. */
export const errorTrackingWidgetFormSchema = z.object({
    limit: widgetLimitFieldSchema,
    orderBy: errorTrackingWidgetConfigSchema.shape.orderBy,
    dateFrom: widgetDateFromSchema,
    filterTestAccounts: z.boolean(),
})

export const sessionReplayWidgetConfigSchema = baseWidgetConfigSchema.extend({
    limit: widgetLimitFieldSchema.default(10),
    orderBy: z
        .enum(['start_time', 'activity_score', 'recording_duration', 'duration', 'click_count', 'console_error_count'])
        .default('start_time'),
    orderDirection: widgetOrderDirectionSchema,
    dateRange: widgetDateRangeSchema,
})

export type SessionReplayWidgetConfig = z.infer<typeof sessionReplayWidgetConfigSchema>

/** Form fields edited in the session replay widget settings modal. */
export const sessionReplayWidgetFormSchema = z.object({
    limit: widgetLimitFieldSchema,
    orderBy: sessionReplayWidgetConfigSchema.shape.orderBy,
    dateFrom: widgetDateFromSchema,
    filterTestAccounts: z.boolean(),
})
