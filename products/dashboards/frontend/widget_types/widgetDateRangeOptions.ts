import { z } from 'zod'

/** Relative `date_from` values allowed on dashboard widget configs (shortest first). */
export const WIDGET_DATE_FROM_VALUES = ['-1h', '-3h', '-24h', '-7d', '-14d', '-30d', '-90d'] as const

export type WidgetDateFromValue = (typeof WIDGET_DATE_FROM_VALUES)[number]

export const widgetDateFromSchema = z.enum(WIDGET_DATE_FROM_VALUES, {
    errorMap: () => ({ message: 'Select a supported date range.' }),
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

export const widgetDateRangeSchema = z
    .object({
        date_from: widgetDateFromSchema.optional(),
        date_to: z.string().optional(),
        explicitDate: z.boolean().optional(),
    })
    .optional()
