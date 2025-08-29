import { z } from 'zod'

export const OverviewRequestSchema = z.object({
    date_from: z.string().nullish(),
    date_to: z.string().nullish(),
    filter_test_account: z.boolean().default(false),
    host: z.string().nullish(),
})

export const OverviewResponseKeySchema = z.enum([
    'visitors',
    'views',
    'sessions',
    'bounce_rate',
    'session_duration',
    'conversion_rate',
    'conversions',
    'revenue',
])

export const OverviewResponseItemSchema = z.object({
    key: OverviewResponseKeySchema,
    label: z.string(),
    value: z.number(),
    previousValue: z.number().nullish(),
    changePercentage: z.number().nullish(),
    isIncreaseGood: z.boolean(),
    format: z.enum(['number', 'percentage', 'currency', 'duration_seconds']).default('number'),
})

export const OverviewResponseSchema = z.record(OverviewResponseKeySchema, OverviewResponseItemSchema)

// Graph schema
export const GraphDataPointSchema = z.object({
    date: z.string(), // ISO date string
    value: z.number(),
    previousValue: z.number().nullish(), // Value from previous period
})

export const GraphResponseSchema = z.object({
    title: z.string().nullish(),
    metric: z.string(), // e.g., "visitors", "pageviews"
    unit: z.string().nullish(), // e.g., "visitors", "%"
    points: z.array(GraphDataPointSchema),
})

// Table schema
export const TableColumnSchema = z.object({
    key: z.string(),
    label: z.string(),
    type: z.enum(['string', 'number', 'percentage']).default('string'),
    sortable: z.boolean().default(true),
})

export const TableRowSchema = z
    .object({
        breakdown_value: z.string(), // The main identifier for the row
        fillRatio: z.number().min(0).max(1).nullish(), // 0-1 for horizontal fill bar
    })
    .catchall(z.union([z.string(), z.number()])) // Allow any additional columns

export const TableResponseSchema = z.object({
    columns: z.array(TableColumnSchema),
    rows: z.array(TableRowSchema),
    count: z.number(),
    next: z.string().nullish(),
    previous: z.string().nullish(),
})

// TypeScript types
export type OverviewResponse = z.infer<typeof OverviewResponseSchema>
export type OverviewResponseKey = keyof OverviewResponse
export type OverviewResponseItem = z.infer<typeof OverviewResponseItemSchema>
export type OverviewResponseFormat = OverviewResponseItem['format']
export type GraphDataPoint = z.infer<typeof GraphDataPointSchema>
export type GraphResponse = z.infer<typeof GraphResponseSchema>
export type TableColumn = z.infer<typeof TableColumnSchema>
export type TableRow = z.infer<typeof TableRowSchema>
export type TableResponse = z.infer<typeof TableResponseSchema>

// Error types
export const ErrorResponseSchema = z.object({
    error: z.string(),
    details: z.string().nullish(),
})

export type ErrorResponse = z.infer<typeof ErrorResponseSchema>
