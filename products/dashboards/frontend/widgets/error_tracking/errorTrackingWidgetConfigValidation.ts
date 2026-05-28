import type { ZodError } from 'zod'

import { ApiError } from 'lib/api-error'

import { errorTrackingWidgetConfigSchema } from '../../widget_types/configSchemas'

const LIMIT_FIELD_ERROR = 'Must be an integer between 1 and 25.'

export type ErrorTrackingWidgetFieldErrors = {
    limit?: string
    orderBy?: string
    dateFrom?: string
}

function zodIssuesToFieldErrors(error: ZodError): ErrorTrackingWidgetFieldErrors {
    const fieldErrors: ErrorTrackingWidgetFieldErrors = {}

    for (const issue of error.issues) {
        const [root] = issue.path
        if (root === 'limit' && !fieldErrors.limit) {
            fieldErrors.limit = issue.path[0] === 'limit' && issue.code === 'too_big' ? LIMIT_FIELD_ERROR : issue.message
        }
        if (root === 'orderBy' && !fieldErrors.orderBy) {
            fieldErrors.orderBy = issue.message
        }
        if (issue.path[0] === 'dateRange' && issue.path[1] === 'date_from' && !fieldErrors.dateFrom) {
            fieldErrors.dateFrom = issue.message
        }
    }

    if (fieldErrors.limit == null && error.issues.some((issue) => issue.path[0] === 'limit')) {
        fieldErrors.limit = LIMIT_FIELD_ERROR
    }

    return fieldErrors
}

export function buildErrorTrackingWidgetConfigInput({
    limit,
    orderBy,
    dateFrom,
    filterTestAccounts,
    baseConfig,
}: {
    limit: number
    orderBy: string
    dateFrom: string
    filterTestAccounts: boolean
    baseConfig: Record<string, unknown>
}): Record<string, unknown> {
    return {
        ...baseConfig,
        limit,
        orderBy,
        filterTestAccounts,
        dateRange: { date_from: dateFrom },
    }
}

export function validateErrorTrackingWidgetConfigInput(input: {
    limit: number
    orderBy: string
    dateFrom: string
    filterTestAccounts: boolean
    baseConfig: Record<string, unknown>
}): { success: true; config: Record<string, unknown> } | { success: false; fieldErrors: ErrorTrackingWidgetFieldErrors } {
    const config = buildErrorTrackingWidgetConfigInput(input)
    const parsed = errorTrackingWidgetConfigSchema.safeParse(config)

    if (parsed.success) {
        return { success: true, config: parsed.data as Record<string, unknown> }
    }

    const fieldErrors = zodIssuesToFieldErrors(parsed.error)
    if (input.limit > 25 || input.limit < 1 || !Number.isInteger(input.limit)) {
        fieldErrors.limit = LIMIT_FIELD_ERROR
    }

    return { success: false, fieldErrors }
}

const LIMIT_API_MESSAGE_PATTERN = /limit must be an integer between 1 and 25/i

export function parseErrorTrackingWidgetConfigApiError(error: unknown): ErrorTrackingWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const data = error.data
    const configMessage = extractConfigValidationMessage(data) ?? extractConfigValidationMessageFromMessage(error.message)

    if (!configMessage) {
        return null
    }

    const fieldErrors: ErrorTrackingWidgetFieldErrors = {}

    if (LIMIT_API_MESSAGE_PATTERN.test(configMessage)) {
        fieldErrors.limit = LIMIT_FIELD_ERROR
    } else if (/orderBy must be one of/i.test(configMessage)) {
        fieldErrors.orderBy = configMessage
    }

    return Object.keys(fieldErrors).length > 0 ? fieldErrors : null
}

function extractConfigValidationMessage(data: unknown): string | null {
    if (!data || typeof data !== 'object') {
        return null
    }

    const record = data as Record<string, unknown>
    const config = record.config

    if (typeof config === 'string') {
        return config
    }
    if (Array.isArray(config) && typeof config[0] === 'string') {
        return config[0]
    }

    const widget = record.widget
    if (widget && typeof widget === 'object') {
        const widgetConfig = (widget as Record<string, unknown>).config
        if (typeof widgetConfig === 'string') {
            return widgetConfig
        }
        if (Array.isArray(widgetConfig) && typeof widgetConfig[0] === 'string') {
            return widgetConfig[0]
        }
    }

    return null
}

function extractConfigValidationMessageFromMessage(message: string): string | null {
    if (LIMIT_API_MESSAGE_PATTERN.test(message) || /orderBy must be one of/i.test(message)) {
        return message
    }
    return null
}
