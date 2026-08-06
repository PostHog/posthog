import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import { logsWidgetConfigSchema, logsWidgetFormSchema, type LogsWidgetConfig } from '../../generated/widget-configs.zod'
import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export const LOGS_DEFAULT_DATE_FROM: WidgetDateFromValue = '-1h'

export type LogsOrderByValue = NonNullable<LogsWidgetConfig['orderBy']>
export type LogsSeverityLevel = NonNullable<LogsWidgetConfig['severityLevels']>[number]
export type LogsTimezone = NonNullable<LogsWidgetConfig['timezone']>

export const LOGS_WIDGET_FORM_FIELD_NAMES = Object.keys(
    logsWidgetFormSchema.shape
) as (keyof typeof logsWidgetFormSchema.shape)[]

type LogsWidgetFormField = keyof z.infer<typeof logsWidgetFormSchema>

export type LogsWidgetFieldErrors = Partial<Record<LogsWidgetFormField, string>>

export type LogsWidgetFormInput = {
    limit: number
    wrapLines: boolean
    timezone: LogsTimezone
    dateRange: { date_from?: string | null } | null
}

const logsConfigDefaults = logsWidgetConfigSchema.parse({})

export function parseLogsWidgetConfig(config: Record<string, unknown>): LogsWidgetConfig {
    return parseWidgetConfig(logsWidgetConfigSchema, config)
}

/** On-tile filter changes (severity, services, sort, saved view) — keeps the rest of the config untouched. */
export function patchLogsWidgetFilterFields(
    config: Record<string, unknown>,
    patch: {
        severityLevels?: LogsSeverityLevel[]
        serviceNames?: string[]
        orderBy?: LogsOrderByValue
        dateFrom?: WidgetDateFromValue
        savedViewId?: string | null
    }
): LogsWidgetConfig {
    const base = parseLogsWidgetConfig(config)

    return logsWidgetConfigSchema.parse({
        ...base,
        severityLevels: patch.severityLevels ?? base.severityLevels,
        serviceNames: patch.serviceNames ?? base.serviceNames,
        orderBy: patch.orderBy ?? base.orderBy,
        dateRange: { date_from: patch.dateFrom ?? base.dateRange?.date_from ?? LOGS_DEFAULT_DATE_FROM },
        // `savedViewId` is intentionally read with `in` so an explicit `null` clears it.
        savedViewId: 'savedViewId' in patch ? patch.savedViewId : base.savedViewId,
    })
}

export function buildLogsWidgetConfig(formInput: LogsWidgetFormInput, baseConfig: LogsWidgetConfig): LogsWidgetConfig {
    return logsWidgetConfigSchema.parse({
        ...baseConfig,
        ...formInput,
    })
}

export function validateLogsWidgetConfigInput(input: {
    limit: number
    wrapLines: boolean
    timezone: LogsTimezone
    dateFrom: WidgetDateFromValue
    baseConfig: LogsWidgetConfig
}): { success: true; config: LogsWidgetConfig } | { success: false; fieldErrors: LogsWidgetFieldErrors } {
    const parsed = logsWidgetFormSchema.safeParse({
        limit: input.limit,
        wrapLines: input.wrapLines,
        timezone: input.timezone,
        dateRange: { date_from: input.dateFrom },
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    const formInput: LogsWidgetFormInput = {
        limit: parsed.data.limit,
        wrapLines: parsed.data.wrapLines,
        timezone: parsed.data.timezone,
        dateRange: parsed.data.dateRange ?? null,
    }

    return {
        success: true,
        config: buildLogsWidgetConfig(formInput, input.baseConfig),
    }
}

export function parseLogsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): LogsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = logsWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = logsWidgetFormSchema.safeParse({
        limit: (config.limit as number) ?? logsConfigDefaults.limit ?? 0,
        wrapLines: (config.wrapLines as boolean) ?? logsConfigDefaults.wrapLines ?? false,
        timezone: (config.timezone as LogsTimezone) ?? logsConfigDefaults.timezone ?? 'UTC',
        dateRange: (config.dateRange as { date_from?: string | null } | undefined) ?? {
            date_from: LOGS_DEFAULT_DATE_FROM,
        },
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
