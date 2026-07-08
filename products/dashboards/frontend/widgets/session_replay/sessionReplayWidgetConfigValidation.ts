import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    sessionReplayWidgetConfigSchema,
    sessionReplayWidgetFormSchema,
    type SessionReplayWidgetConfig,
    type StoredWidgetFilter,
} from '../../generated/widget-configs.zod'
import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig, type WidgetListFormInput } from '../widgetConfigValidation'

export const SESSION_REPLAY_WIDGET_FORM_FIELD_NAMES = Object.keys(
    sessionReplayWidgetFormSchema.shape
) as (keyof typeof sessionReplayWidgetFormSchema.shape)[]

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
        savedFilterId?: string | null
        collectionId?: string | null
    }
): SessionReplayWidgetConfig {
    const base = parseSessionReplayWidgetConfig(config)
    // A collection (scope) and a saved filter (refinement) are independent — each patches only its own field.
    const savedFilterId = patch.savedFilterId !== undefined ? patch.savedFilterId : (base.savedFilterId ?? null)
    const collectionId = patch.collectionId !== undefined ? patch.collectionId : (base.collectionId ?? null)

    return sessionReplayWidgetConfigSchema.parse({
        ...base,
        dateRange: { date_from: patch.dateFrom ?? base.dateRange?.date_from ?? '-7d' },
        widgetFilters: patch.widgetFilters ?? base.widgetFilters ?? {},
        savedFilterId,
        collectionId,
    })
}

export function buildSessionReplayWidgetConfig(
    formInput: SessionReplayWidgetFormInput,
    baseConfig: SessionReplayWidgetConfig
): SessionReplayWidgetConfig {
    return sessionReplayWidgetConfigSchema.parse({
        ...baseConfig,
        ...formInput,
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
        dateRange: { date_from: input.baseConfig.dateRange?.date_from ?? '-7d' },
        filterTestAccounts: input.filterTestAccounts,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    const formInput: SessionReplayWidgetFormInput = {
        limit: parsed.data.limit,
        orderBy: parsed.data.orderBy,
        orderDirection: parsed.data.orderDirection,
        dateRange: parsed.data.dateRange ?? null,
        filterTestAccounts: parsed.data.filterTestAccounts ?? null,
    }

    return {
        success: true,
        config: buildSessionReplayWidgetConfig(formInput, input.baseConfig),
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
        limit: (config.limit as number) ?? sessionReplayConfigDefaults.limit ?? 0,
        orderBy: (config.orderBy as string) ?? sessionReplayConfigDefaults.orderBy ?? '',
        orderDirection: (config.orderDirection as string) ?? sessionReplayConfigDefaults.orderDirection ?? 'DESC',
        dateRange: (config.dateRange as { date_from?: string | null } | undefined) ?? { date_from: '-7d' },
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
