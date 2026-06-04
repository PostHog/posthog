import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    errorTrackingWidgetConfigSchema,
    errorTrackingWidgetFormSchema,
    type ErrorTrackingWidgetConfig,
    type ErrorTrackingWidgetFormStatus,
} from '../../widget_types/configSchemas'
import type { StoredWidgetFilter } from '../../widget_types/configSchemas'
import { fieldErrorsFromZodError, parseWidgetConfig, type WidgetListFormInput } from '../widgetConfigValidation'
type ErrorTrackingWidgetFormField = keyof z.infer<typeof errorTrackingWidgetFormSchema>

export type ErrorTrackingWidgetFieldErrors = Partial<Record<ErrorTrackingWidgetFormField, string>>

export type ErrorTrackingWidgetFormInput = WidgetListFormInput & {
    orderDirection: ErrorTrackingWidgetConfig['orderDirection']
}

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
        status: patch.status ?? base.status ?? 'active',
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
        orderDirection: input.orderDirection,
        dateFrom: input.baseConfig.dateRange?.date_from ?? '-7d',
        filterTestAccounts: input.filterTestAccounts,
        status: input.baseConfig.status ?? 'active',
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return {
        success: true,
        config: buildErrorTrackingWidgetConfig(parsed.data, input.baseConfig),
    }
}

export function parseErrorTrackingWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ErrorTrackingWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = errorTrackingWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = errorTrackingWidgetFormSchema.safeParse({
        limit: (config.limit as number) ?? 0,
        orderBy: (config.orderBy as string) ?? 'occurrences',
        orderDirection: (config.orderDirection as ErrorTrackingWidgetConfig['orderDirection']) ?? 'DESC',
        dateFrom: (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d',
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
        status: (config.status as ErrorTrackingWidgetFormStatus) ?? 'active',
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
