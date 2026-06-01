import type { ZodError } from 'zod'

import { ApiError } from 'lib/api-error'

import { sessionReplayWidgetConfigSchema } from '../../widget_types/configSchemas'

export type SessionReplayWidgetFieldErrors = {
    limit?: string
    orderBy?: string
    dateFrom?: string
}

function zodIssuesToFieldErrors(error: ZodError): SessionReplayWidgetFieldErrors {
    const fieldErrors: SessionReplayWidgetFieldErrors = {}

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

export function buildSessionReplayWidgetConfigInput({
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

export function validateSessionReplayWidgetConfigInput(input: {
    limit: number
    orderBy: string
    dateFrom: string
    filterTestAccounts: boolean
    baseConfig: Record<string, unknown>
}):
    | { success: true; config: Record<string, unknown> }
    | { success: false; fieldErrors: SessionReplayWidgetFieldErrors } {
    const parsed = sessionReplayWidgetConfigSchema.safeParse(buildSessionReplayWidgetConfigInput(input))

    if (parsed.success) {
        return { success: true, config: parsed.data as Record<string, unknown> }
    }

    return { success: false, fieldErrors: zodIssuesToFieldErrors(parsed.error) }
}

export function parseSessionReplayWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): SessionReplayWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsed = sessionReplayWidgetConfigSchema.safeParse(config)
    if (!parsed.success) {
        return zodIssuesToFieldErrors(parsed.error)
    }

    return null
}
