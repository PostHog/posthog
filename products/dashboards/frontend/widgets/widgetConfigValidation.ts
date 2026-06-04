import { z, type ZodError, type ZodType } from 'zod'

import { ApiError } from 'lib/api-error'

import { widgetFilterEntrySchema, type StoredWidgetFilter } from '../widget_types/configSchemas'

export function fieldErrorsFromZodError<TField extends string>(error: ZodError): Partial<Record<TField, string>> {
    const { fieldErrors } = z.flattenError(error)

    return Object.fromEntries(
        (Object.entries(fieldErrors) as [string, string[]][]).flatMap(([field, messages]) =>
            messages.length > 0 ? [[field, messages[0]]] : []
        )
    ) as Partial<Record<TField, string>>
}

export function parseWidgetConfig<T>(configSchema: ZodType<T>, config: Record<string, unknown>): T {
    const parsed = configSchema.safeParse(config)
    return parsed.success ? parsed.data : configSchema.parse({})
}

export type WidgetListFormInput = {
    limit: number
    orderBy: string
    dateFrom: string
    filterTestAccounts: boolean
}

export type WidgetListFormInputWithWidgetFilters = WidgetListFormInput & {
    widgetFilters: Record<string, StoredWidgetFilter>
}

/** Validated `widgetFilters` patch for widget config builders (omit key when empty). */
export function widgetFiltersPatchFromForm(widgetFilters: Record<string, StoredWidgetFilter>): {
    widgetFilters?: Record<string, StoredWidgetFilter>
} {
    const widgetFiltersParsed = widgetFilterEntrySchema.array().safeParse(Object.values(widgetFilters))
    if (!widgetFiltersParsed.success || Object.keys(widgetFilters).length === 0) {
        return {}
    }
    return { widgetFilters }
}

export function buildWidgetConfigFromForm<TConfig>(
    configSchema: ZodType<TConfig>,
    formInput: WidgetListFormInput,
    baseConfig: TConfig
): TConfig {
    return configSchema.parse({
        ...baseConfig,
        limit: formInput.limit,
        orderBy: formInput.orderBy,
        filterTestAccounts: formInput.filterTestAccounts,
        dateRange: { date_from: formInput.dateFrom },
    })
}

export function validateWidgetConfigInput<TField extends string, TConfig>({
    formSchema,
    buildConfig,
    input,
}: {
    formSchema: ZodType<WidgetListFormInput>
    buildConfig: (formInput: WidgetListFormInput, baseConfig: TConfig) => TConfig
    input: WidgetListFormInput & { baseConfig: TConfig }
}): { success: true; config: TConfig } | { success: false; fieldErrors: Partial<Record<TField, string>> } {
    const parsed = formSchema.safeParse({
        limit: input.limit,
        orderBy: input.orderBy,
        dateFrom: input.dateFrom,
        filterTestAccounts: input.filterTestAccounts,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError<TField>(parsed.error) }
    }

    return {
        success: true,
        config: buildConfig(parsed.data, input.baseConfig),
    }
}

export function parseWidgetConfigApiError<TField extends string, TConfig>({
    error,
    config,
    configSchema,
    formSchema,
    defaultOrderBy,
}: {
    error: unknown
    config: Record<string, unknown>
    configSchema: ZodType<TConfig>
    formSchema: ZodType<WidgetListFormInput>
    defaultOrderBy: string
}): Partial<Record<TField, string>> | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = configSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const formInput: WidgetListFormInput = {
        limit: (config.limit as number) ?? 0,
        orderBy: (config.orderBy as string) ?? defaultOrderBy,
        dateFrom: (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d',
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
    }
    const parsedForm = formSchema.safeParse(formInput)
    if (!parsedForm.success) {
        return fieldErrorsFromZodError<TField>(parsedForm.error)
    }

    return fieldErrorsFromZodError<TField>(parsedConfig.error)
}
