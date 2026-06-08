import { z } from 'zod'

import {
    errorTrackingWidgetConfigSchema,
    errorTrackingWidgetFormSchema,
    type ErrorTrackingWidgetConfig,
    type ErrorTrackingWidgetFormStatus,
} from '../../widget_types/configSchemas'
import type { StoredWidgetFilter } from '../../widget_types/configSchemas'
import {
    fieldErrorsFromZodError,
    parseWidgetConfig,
    parseWidgetConfigApiError,
    type WidgetListFormInput,
} from '../widgetConfigValidation'

type ErrorTrackingWidgetFormField = keyof z.infer<typeof errorTrackingWidgetFormSchema>

export type ErrorTrackingWidgetFieldErrors = Partial<Record<ErrorTrackingWidgetFormField, string>>

export type ErrorTrackingWidgetFormInput = WidgetListFormInput & {
    orderDirection: ErrorTrackingWidgetConfig['orderDirection']
}

const errorTrackingConfigDefaults = errorTrackingWidgetConfigSchema.parse({})

export function parseErrorTrackingWidgetConfig(config: Record<string, unknown>): ErrorTrackingWidgetConfig {
    return parseWidgetConfig(errorTrackingWidgetConfigSchema, config)
}

export function patchErrorTrackingWidgetFilterFields(
    config: Record<string, unknown>,
    patch: {
        dateFrom?: string
        status?: ErrorTrackingWidgetFormStatus
        assignee?: ErrorTrackingWidgetConfig['assignee'] | null
        widgetFilters?: Record<string, StoredWidgetFilter>
    }
): ErrorTrackingWidgetConfig {
    const base = parseErrorTrackingWidgetConfig(config)

    return errorTrackingWidgetConfigSchema.parse({
        ...base,
        dateRange: { date_from: patch.dateFrom ?? base.dateRange?.date_from ?? '-7d' },
        status: patch.status ?? base.status ?? errorTrackingConfigDefaults.status,
        assignee: patch.assignee !== undefined ? (patch.assignee ?? undefined) : base.assignee,
        widgetFilters: patch.widgetFilters ?? base.widgetFilters ?? {},
    })
}

export function buildErrorTrackingWidgetConfig(
    formInput: ErrorTrackingWidgetFormInput,
    baseConfig: ErrorTrackingWidgetConfig
): ErrorTrackingWidgetConfig {
    return errorTrackingWidgetConfigSchema.parse({
        ...baseConfig,
        limit: formInput.limit,
        orderBy: formInput.orderBy,
        orderDirection: formInput.orderDirection,
        filterTestAccounts: formInput.filterTestAccounts,
    })
}

export function validateErrorTrackingWidgetConfigInput(input: {
    limit: number
    orderBy: string
    orderDirection: string
    filterTestAccounts: boolean
    baseConfig: ErrorTrackingWidgetConfig
}):
    | { success: true; config: ErrorTrackingWidgetConfig }
    | { success: false; fieldErrors: ErrorTrackingWidgetFieldErrors } {
    const parsed = errorTrackingWidgetFormSchema.safeParse({
        limit: input.limit,
        orderBy: input.orderBy,
        dateFrom: input.baseConfig.dateRange?.date_from ?? '-7d',
        filterTestAccounts: input.filterTestAccounts,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return {
        success: true,
        config: buildErrorTrackingWidgetConfig(
            {
                ...parsed.data,
                orderDirection: input.orderDirection as ErrorTrackingWidgetConfig['orderDirection'],
            },
            input.baseConfig
        ),
    }
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
        defaultOrderBy: errorTrackingConfigDefaults.orderBy,
    })
}
