import { ApiError } from 'lib/api-error'

import { metricsWidgetConfigSchema } from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError } from '../widgetConfigValidation'

export type MetricsWidgetFieldErrors = Partial<Record<'query', string>>

export function parseMetricsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): MetricsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = metricsWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    return fieldErrorsFromZodError(parsedConfig.error) as MetricsWidgetFieldErrors
}
