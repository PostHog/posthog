import { z } from 'zod'

import {
    sessionReplayWidgetConfigSchema,
    sessionReplayWidgetFormSchema,
    type SessionReplayWidgetConfig,
    type StoredWidgetFilter,
    type WidgetDateFromValue,
} from '../../widget_types/configSchemas'
import {
    parseWidgetConfig,
    parseWidgetConfigApiError,
    validateWidgetConfigInput,
    type WidgetListFormInput,
} from '../widgetConfigValidation'

type SessionReplayWidgetFormField = keyof z.infer<typeof sessionReplayWidgetFormSchema>

export type SessionReplayWidgetFieldErrors = Partial<Record<SessionReplayWidgetFormField, string>>

export type SessionReplayWidgetFormInput = WidgetListFormInput & {
    orderDirection: SessionReplayWidgetConfig['orderDirection']
}

const sessionReplayConfigDefaults = sessionReplayWidgetConfigSchema.parse({})

export function parseSessionReplayWidgetConfig(config: Record<string, unknown>): SessionReplayWidgetConfig {
    return parseWidgetConfig(sessionReplayWidgetConfigSchema, config)
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
    return validateWidgetConfigInput({
        formSchema: sessionReplayWidgetFormSchema,
        buildConfig: (formInput) =>
            buildSessionReplayWidgetConfig(
                {
                    ...formInput,
                    orderDirection: input.orderDirection as SessionReplayWidgetConfig['orderDirection'],
                },
                input.baseConfig
            ),
        input: {
            limit: input.limit,
            orderBy: input.orderBy,
            dateFrom: input.baseConfig.dateRange?.date_from ?? '-7d',
            filterTestAccounts: input.filterTestAccounts,
            baseConfig: input.baseConfig,
        },
    })
}

export function parseSessionReplayWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): SessionReplayWidgetFieldErrors | null {
    return parseWidgetConfigApiError({
        error,
        config,
        configSchema: sessionReplayWidgetConfigSchema,
        formSchema: sessionReplayWidgetFormSchema,
        defaultOrderBy: sessionReplayConfigDefaults.orderBy,
    })
}
