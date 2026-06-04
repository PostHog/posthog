import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    normalizeWidgetConfigKeys,
    sessionReplayWidgetConfigSchema,
    sessionReplayWidgetFormSchema,
    type SessionReplayWidgetConfig,
    type StoredWidgetFilter,
    type WidgetDateFromValue,
} from '../../widget_types/configSchemas'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'
type SessionReplayWidgetFormField = keyof z.infer<typeof sessionReplayWidgetFormSchema>

export type SessionReplayWidgetFieldErrors = Partial<Record<SessionReplayWidgetFormField, string>>

export type SessionReplayWidgetFormInput = {
    limit: number
    orderBy: string
    orderDirection: SessionReplayWidgetConfig['orderDirection']
    filterTestAccounts: boolean
}

export function parseSessionReplayWidgetConfig(config: Record<string, unknown>): SessionReplayWidgetConfig {
    return parseWidgetConfig(sessionReplayWidgetConfigSchema, normalizeWidgetConfigKeys(config))
}

export function patchSessionReplayWidgetFilterFields(
    config: Record<string, unknown>,
    patch: {
        dateFrom?: WidgetDateFromValue
        widgetFilters?: Record<string, StoredWidgetFilter>
    }
): SessionReplayWidgetConfig {
    const base = parseSessionReplayWidgetConfig(config)

    return sessionReplayWidgetConfigSchema.parse({
        ...base,
        dateRange: { date_from: patch.dateFrom ?? base.dateRange?.date_from ?? '-7d' },
        widgetFilters: patch.widgetFilters ?? base.widgetFilters ?? {},
    })
}

export function buildSessionReplayWidgetConfig(
    formInput: SessionReplayWidgetFormInput,
    baseConfig: SessionReplayWidgetConfig
): SessionReplayWidgetConfig {
    return sessionReplayWidgetConfigSchema.parse({
        ...baseConfig,
        limit: formInput.limit,
        orderBy: formInput.orderBy,
        orderDirection: formInput.orderDirection,
        filterTestAccounts: formInput.filterTestAccounts,
    })
}

export function validateSessionReplayWidgetConfigInput(input: {
    limit: number
    orderBy: string
    orderDirection: string
    filterTestAccounts: boolean
    baseConfig: SessionReplayWidgetConfig
}):
    | { success: true; config: SessionReplayWidgetConfig }
    | { success: false; fieldErrors: SessionReplayWidgetFieldErrors } {
    const parsed = sessionReplayWidgetFormSchema.safeParse({
        limit: input.limit,
        orderBy: input.orderBy,
        orderDirection: input.orderDirection,
        dateFrom: input.baseConfig.dateRange?.date_from ?? '-7d',
        filterTestAccounts: input.filterTestAccounts,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return {
        success: true,
        config: buildSessionReplayWidgetConfig(parsed.data, input.baseConfig),
    }
}

export function parseSessionReplayWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): SessionReplayWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = sessionReplayWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = sessionReplayWidgetFormSchema.safeParse({
        limit: (config.limit as number) ?? 0,
        orderBy: (config.orderBy as string) ?? 'start_time',
        orderDirection: (config.orderDirection as SessionReplayWidgetConfig['orderDirection']) ?? 'DESC',
        dateFrom: (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d',
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
