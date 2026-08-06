import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import type { ErrorTrackingQuery } from '~/queries/schema/schema-general'

import {
    errorTrackingWidgetConfigSchema,
    errorTrackingWidgetFormSchema,
    type ErrorTrackingWidgetConfig,
    type StoredWidgetFilter,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig, type WidgetListFormInput } from '../widgetConfigValidation'

export type ErrorTrackingWidgetFormStatus = NonNullable<ErrorTrackingQuery['status']> | 'all'

export const ERROR_TRACKING_WIDGET_FORM_FIELD_NAMES = Object.keys(
    errorTrackingWidgetFormSchema.shape
) as (keyof typeof errorTrackingWidgetFormSchema.shape)[]

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
        ...formInput,
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
        dateRange: { date_from: input.baseConfig.dateRange?.date_from ?? '-7d' },
        filterTestAccounts: input.filterTestAccounts,
        status: (input.baseConfig.status ?? errorTrackingConfigDefaults.status) as ErrorTrackingWidgetFormStatus,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    const formInput: ErrorTrackingWidgetFormInput = {
        limit: parsed.data.limit,
        orderBy: parsed.data.orderBy,
        orderDirection: parsed.data.orderDirection,
        dateRange: parsed.data.dateRange ?? null,
        filterTestAccounts: parsed.data.filterTestAccounts ?? null,
    }

    return {
        success: true,
        config: buildErrorTrackingWidgetConfig(formInput, input.baseConfig),
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
        limit: (config.limit as number) ?? errorTrackingConfigDefaults.limit ?? 0,
        orderBy: (config.orderBy as string) ?? errorTrackingConfigDefaults.orderBy ?? '',
        orderDirection: (config.orderDirection as string) ?? errorTrackingConfigDefaults.orderDirection ?? 'DESC',
        dateRange: (config.dateRange as { date_from?: string | null } | undefined) ?? { date_from: '-7d' },
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
        status: (config.status as ErrorTrackingWidgetFormStatus) ?? errorTrackingConfigDefaults.status ?? 'active',
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
