import type { ZodError } from 'zod'

import { ApiError } from 'lib/api-error'

import { errorTrackingWidgetConfigSchema } from '../../widget_types/configSchemas'

export type ErrorTrackingWidgetFieldErrors = {
    limit?: string
    orderBy?: string
    dateFrom?: string
}

function zodIssuesToFieldErrors(error: ZodError): ErrorTrackingWidgetFieldErrors {
    const fieldErrors: ErrorTrackingWidgetFieldErrors = {}

    for (const issue of error.issues) {
        if (issue.path[0] === 'dateRange' && issue.path[1] === 'date_from') {
            fieldErrors.dateFrom ??= issue.message
            continue
        }

        if (issue.path[0] === 'limit') {
            fieldErrors.limit ??= issue.message
        } else if (issue.path[0] === 'orderBy') {
            fieldErrors.orderBy ??= issue.message
        }
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
}):
    | { success: true; config: Record<string, unknown> }
    | { success: false; fieldErrors: ErrorTrackingWidgetFieldErrors } {
    const parsed = errorTrackingWidgetConfigSchema.safeParse(buildErrorTrackingWidgetConfigInput(input))

    if (parsed.success) {
        return { success: true, config: parsed.data as Record<string, unknown> }
    }

    return { success: false, fieldErrors: zodIssuesToFieldErrors(parsed.error) }
}

export function parseErrorTrackingWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ErrorTrackingWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsed = errorTrackingWidgetConfigSchema.safeParse(config)
    if (!parsed.success) {
        return zodIssuesToFieldErrors(parsed.error)
    }

    return null
}
