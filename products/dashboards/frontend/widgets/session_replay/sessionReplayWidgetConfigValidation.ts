import { z, type ZodError } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    sessionReplayWidgetConfigSchema,
    type SessionReplayWidgetConfig,
    widgetDateFromSchema,
    widgetLimitFieldSchema,
} from '../../widget_types/configSchemas'

export type SessionReplayWidgetFieldErrors = Partial<Record<keyof SessionReplayWidgetFormInput, string>>

export const sessionReplayWidgetFormSchema = z.object({
    limit: widgetLimitFieldSchema,
    orderBy: sessionReplayWidgetConfigSchema.shape.orderBy,
    dateFrom: widgetDateFromSchema,
    filterTestAccounts: z.boolean(),
})

export type SessionReplayWidgetFormInput = z.infer<typeof sessionReplayWidgetFormSchema>

function fieldErrorsFromZodError(error: ZodError): SessionReplayWidgetFieldErrors {
    const { fieldErrors } = z.flattenError(error)

    return Object.fromEntries(
        Object.entries(fieldErrors).flatMap(([field, messages]) =>
            messages.length > 0 ? [[field, messages[0] as string]] : []
        )
    )
}

export function parseSessionReplayWidgetConfig(config: Record<string, unknown>): SessionReplayWidgetConfig {
    const parsed = sessionReplayWidgetConfigSchema.safeParse(config)
    return parsed.success ? parsed.data : sessionReplayWidgetConfigSchema.parse({})
}

export function buildSessionReplayWidgetConfig(
    formInput: SessionReplayWidgetFormInput,
    baseConfig: SessionReplayWidgetConfig
): SessionReplayWidgetConfig {
    return sessionReplayWidgetConfigSchema.parse({
        ...baseConfig,
        limit: formInput.limit,
        orderBy: formInput.orderBy,
        filterTestAccounts: formInput.filterTestAccounts,
        dateRange: { date_from: formInput.dateFrom },
    })
}

export function validateSessionReplayWidgetConfigInput(input: {
    limit: number
    orderBy: string
    dateFrom: string
    filterTestAccounts: boolean
    baseConfig: SessionReplayWidgetConfig
}):
    | { success: true; config: SessionReplayWidgetConfig }
    | { success: false; fieldErrors: SessionReplayWidgetFieldErrors } {
    const parsed = sessionReplayWidgetFormSchema.safeParse({
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

    const formInput: SessionReplayWidgetFormInput = {
        limit: (config.limit as number) ?? 0,
        orderBy: (config.orderBy as SessionReplayWidgetFormInput['orderBy']) ?? 'start_time',
        dateFrom: (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d',
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
    }
    const parsedForm = sessionReplayWidgetFormSchema.safeParse(formInput)
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
