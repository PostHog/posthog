import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    metricsTableWidgetConfigSchema,
    metricsTableWidgetFormSchema,
    type MetricsTableWidgetConfig,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export type MetricsTableColumn = NonNullable<MetricsTableWidgetConfig['columns']>[number]
export type MetricsTableAggregation = MetricsTableColumn['aggregation']
type MetricsTableWidgetFormField = keyof z.infer<typeof metricsTableWidgetFormSchema>
export type MetricsTableWidgetFieldErrors = Partial<Record<MetricsTableWidgetFormField, string>>

export function parseMetricsTableWidgetConfig(config: Record<string, unknown>): MetricsTableWidgetConfig {
    return parseWidgetConfig(metricsTableWidgetConfigSchema, config)
}

export function parseMetricsTableWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): MetricsTableWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }
    const parsed = metricsTableWidgetConfigSchema.safeParse(config)
    return parsed.success ? null : fieldErrorsFromZodError(parsed.error)
}
