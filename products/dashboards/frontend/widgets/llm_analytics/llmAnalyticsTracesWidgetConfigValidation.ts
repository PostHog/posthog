import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    llmAnalyticsTracesWidgetConfigSchema,
    llmAnalyticsTracesWidgetFormSchema,
    type LlmAnalyticsTracesWidgetConfig,
} from '../../generated/widget-configs.zod'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export const LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM: WidgetDateFromValue = '-7d'

export const LLM_ANALYTICS_TRACES_WIDGET_FORM_FIELD_NAMES = Object.keys(
    llmAnalyticsTracesWidgetFormSchema.shape
) as (keyof typeof llmAnalyticsTracesWidgetFormSchema.shape)[]

type LlmAnalyticsTracesWidgetFormField = keyof z.infer<typeof llmAnalyticsTracesWidgetFormSchema>

export type LlmAnalyticsTracesWidgetFieldErrors = Partial<Record<LlmAnalyticsTracesWidgetFormField, string>>

export type LlmAnalyticsTracesWidgetFormInput = {
    limit: number
    dateRange: { date_from?: string | null } | null
    filterTestAccounts: boolean | null
    filterSupportTraces: boolean | null
}

const llmAnalyticsTracesConfigDefaults = llmAnalyticsTracesWidgetConfigSchema.parse({})

const ALLOWED_DATE_FROM_VALUES = new Set<string>(WIDGET_DATE_RANGE_SELECT_OPTIONS.map((option) => option.value))

/** Saved AIO filters can carry any HogQL date string; widget configs only allow a fixed set. */
export function clampToWidgetDateFrom(dateFrom: string | null | undefined): WidgetDateFromValue {
    if (dateFrom && ALLOWED_DATE_FROM_VALUES.has(dateFrom)) {
        return dateFrom as WidgetDateFromValue
    }
    return LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM
}

export type LlmAnalyticsTracesSavedFilterValues = {
    dateFrom: WidgetDateFromValue
    filterTestAccounts: boolean | null
    filterSupportTraces: boolean | null
}

/** Extracts the scalar fields a widget config can store from a saved AIO trace filter's TracesQuery source. */
export function extractSavedFilterValues(
    source: Record<string, unknown> | null | undefined
): LlmAnalyticsTracesSavedFilterValues {
    const dateRange = source?.dateRange as { date_from?: string | null } | undefined
    const filterTestAccounts = source?.filterTestAccounts
    const filterSupportTraces = source?.filterSupportTraces

    return {
        dateFrom: clampToWidgetDateFrom(dateRange?.date_from),
        filterTestAccounts: typeof filterTestAccounts === 'boolean' ? filterTestAccounts : null,
        filterSupportTraces: typeof filterSupportTraces === 'boolean' ? filterSupportTraces : null,
    }
}

export function parseLlmAnalyticsTracesWidgetConfig(config: Record<string, unknown>): LlmAnalyticsTracesWidgetConfig {
    return parseWidgetConfig(llmAnalyticsTracesWidgetConfigSchema, config)
}

export function patchLlmAnalyticsTracesWidgetFilterFields(
    config: Record<string, unknown>,
    patch: {
        dateFrom?: WidgetDateFromValue
    }
): LlmAnalyticsTracesWidgetConfig {
    const base = parseLlmAnalyticsTracesWidgetConfig(config)

    return llmAnalyticsTracesWidgetConfigSchema.parse({
        ...base,
        dateRange: {
            date_from: patch.dateFrom ?? base.dateRange?.date_from ?? LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
        },
    })
}

export function buildLlmAnalyticsTracesWidgetConfig(
    formInput: LlmAnalyticsTracesWidgetFormInput,
    baseConfig: LlmAnalyticsTracesWidgetConfig
): LlmAnalyticsTracesWidgetConfig {
    return llmAnalyticsTracesWidgetConfigSchema.parse({
        ...baseConfig,
        ...formInput,
    })
}

export function validateLlmAnalyticsTracesWidgetConfigInput(input: {
    limit: number
    filterTestAccounts: boolean
    filterSupportTraces: boolean
    dateFrom?: WidgetDateFromValue
    baseConfig: LlmAnalyticsTracesWidgetConfig
}):
    | { success: true; config: LlmAnalyticsTracesWidgetConfig }
    | { success: false; fieldErrors: LlmAnalyticsTracesWidgetFieldErrors } {
    const dateFrom = input.dateFrom ?? input.baseConfig.dateRange?.date_from ?? LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM
    const parsed = llmAnalyticsTracesWidgetFormSchema.safeParse({
        limit: input.limit,
        dateRange: { date_from: dateFrom },
        filterTestAccounts: input.filterTestAccounts,
        filterSupportTraces: input.filterSupportTraces,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    const formInput: LlmAnalyticsTracesWidgetFormInput = {
        limit: parsed.data.limit,
        dateRange: parsed.data.dateRange ?? null,
        filterTestAccounts: parsed.data.filterTestAccounts ?? null,
        filterSupportTraces: parsed.data.filterSupportTraces ?? null,
    }

    return {
        success: true,
        config: buildLlmAnalyticsTracesWidgetConfig(formInput, input.baseConfig),
    }
}

export function parseLlmAnalyticsTracesWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): LlmAnalyticsTracesWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = llmAnalyticsTracesWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = llmAnalyticsTracesWidgetFormSchema.safeParse({
        limit: (config.limit as number) ?? llmAnalyticsTracesConfigDefaults.limit ?? 0,
        dateRange: (config.dateRange as { date_from?: string | null } | undefined) ?? {
            date_from: LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
        },
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
        filterSupportTraces: (config.filterSupportTraces as boolean) ?? false,
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
