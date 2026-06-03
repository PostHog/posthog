import { z } from 'zod'

import {
    errorTrackingWidgetConfigSchema,
    errorTrackingWidgetFormSchema,
    type ErrorTrackingWidgetConfig,
} from '../../widget_types/configSchemas'
import {
    buildWidgetConfigFromForm,
    parseWidgetConfig,
    parseWidgetConfigApiError,
    type WidgetListFormInput,
    validateWidgetConfigInput as validateWidgetConfigInputShared,
} from '../widgetConfigValidation'

type ErrorTrackingWidgetFormField = keyof z.infer<typeof errorTrackingWidgetFormSchema>

export type ErrorTrackingWidgetFieldErrors = Partial<Record<ErrorTrackingWidgetFormField, string>>

export function parseErrorTrackingWidgetConfig(config: Record<string, unknown>): ErrorTrackingWidgetConfig {
    return parseWidgetConfig(errorTrackingWidgetConfigSchema, config)
}

export function buildErrorTrackingWidgetConfig(
    formInput: WidgetListFormInput,
    baseConfig: ErrorTrackingWidgetConfig
): ErrorTrackingWidgetConfig {
    return buildWidgetConfigFromForm(errorTrackingWidgetConfigSchema, formInput, baseConfig)
}

export function validateErrorTrackingWidgetConfigInput(input: {
    limit: number
    orderBy: string
    dateFrom: string
    filterTestAccounts: boolean
    baseConfig: ErrorTrackingWidgetConfig
}):
    | { success: true; config: ErrorTrackingWidgetConfig }
    | { success: false; fieldErrors: ErrorTrackingWidgetFieldErrors } {
    return validateWidgetConfigInputShared({
        formSchema: errorTrackingWidgetFormSchema,
        buildConfig: buildErrorTrackingWidgetConfig,
        input,
    })
}

export function parseErrorTrackingWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ErrorTrackingWidgetFieldErrors | null {
    return parseWidgetConfigApiError({
        error,
        config,
        configSchema: errorTrackingWidgetConfigSchema,
        formSchema: errorTrackingWidgetFormSchema,
        defaultOrderBy: 'occurrences',
    })
}
