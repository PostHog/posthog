import { z, type ZodError } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    errorTrackingWidgetConfigSchema,
    type ErrorTrackingWidgetConfig,
    widgetDateFromSchema,
    widgetLimitFieldSchema,
} from '../../widget_types/configSchemas'

export type ErrorTrackingWidgetFieldErrors = Partial<Record<keyof ErrorTrackingWidgetFormInput, string>>

export const errorTrackingWidgetFormSchema = z.object({
    limit: widgetLimitFieldSchema,
    orderBy: errorTrackingWidgetConfigSchema.shape.orderBy,
    dateFrom: widgetDateFromSchema,
    filterTestAccounts: z.boolean(),
})

export type ErrorTrackingWidgetFormInput = z.infer<typeof errorTrackingWidgetFormSchema>

function fieldErrorsFromZodError(error: ZodError): ErrorTrackingWidgetFieldErrors {
    const { fieldErrors } = z.flattenError(error)

    return Object.fromEntries(
        Object.entries(fieldErrors).flatMap(([field, messages]) =>
            messages.length > 0 ? [[field, messages[0] as string]] : []
        )
    )
}

export function parseErrorTrackingWidgetConfig(config: Record<string, unknown>): ErrorTrackingWidgetConfig {
    const parsed = errorTrackingWidgetConfigSchema.safeParse(config)
    return parsed.success ? parsed.data : errorTrackingWidgetConfigSchema.parse({})
}

export function buildErrorTrackingWidgetConfig(
    formInput: ErrorTrackingWidgetFormInput,
    baseConfig: ErrorTrackingWidgetConfig
): ErrorTrackingWidgetConfig {
    return errorTrackingWidgetConfigSchema.parse({
        ...baseConfig,
        limit: formInput.limit,
        orderBy: formInput.orderBy,
        filterTestAccounts: formInput.filterTestAccounts,
        dateRange: { date_from: formInput.dateFrom },
    })
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
    const parsed = errorTrackingWidgetFormSchema.safeParse({
        limit: input.limit,
        orderBy: input.orderBy,
        dateFrom: input.dateFrom,
        filterTestAccounts: input.filterTestAccounts,
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

    const formInput: ErrorTrackingWidgetFormInput = {
        limit: (config.limit as number) ?? 0,
        orderBy: (config.orderBy as ErrorTrackingWidgetFormInput['orderBy']) ?? 'occurrences',
        dateFrom: (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d',
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
    }
    const parsedForm = errorTrackingWidgetFormSchema.safeParse(formInput)
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
