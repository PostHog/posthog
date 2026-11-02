import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    metricsTableWidgetConfigSchema,
    metricsTableWidgetFormSchema,
    type MetricsTableWidgetConfig,
} from '../../generated/widget-configs.zod'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export { metricsTableWidgetConfigLimitMax as METRICS_TABLE_MAX_LIMIT } from '../../generated/widget-config-schemas/metricsTableWidgetConfig.zod'

/** Metrics queries span at most 31 days, so longer presets are left out. Matches the backend config check. */
export const METRICS_TABLE_DATE_RANGE_OPTIONS = WIDGET_DATE_RANGE_SELECT_OPTIONS.filter(
    (option) => option.value !== '-90d'
)

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
