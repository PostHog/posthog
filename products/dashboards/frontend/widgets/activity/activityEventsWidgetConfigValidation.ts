import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    activityEventsWidgetConfigSchema,
    activityEventsWidgetFormSchema,
    type ActivityEventsWidgetConfig,
} from '../../generated/widget-configs.zod'
import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export const ACTIVITY_EVENTS_DEFAULT_DATE_FROM: WidgetDateFromValue = '-24h'

export const ACTIVITY_EVENTS_WIDGET_FORM_FIELD_NAMES = Object.keys(
    activityEventsWidgetFormSchema.shape
) as (keyof typeof activityEventsWidgetFormSchema.shape)[]

type ActivityEventsWidgetFormField = keyof z.infer<typeof activityEventsWidgetFormSchema>

export type ActivityEventsWidgetFieldErrors = Partial<Record<ActivityEventsWidgetFormField, string>>

export type ActivityEventsWidgetFormInput = {
    limit: number
    dateRange: { date_from?: string | null } | null
    filterTestAccounts: boolean | null
}

const activityEventsConfigDefaults = activityEventsWidgetConfigSchema.parse({})

export function parseActivityEventsWidgetConfig(config: Record<string, unknown>): ActivityEventsWidgetConfig {
    return parseWidgetConfig(activityEventsWidgetConfigSchema, config)
}

export function patchActivityEventsWidgetFilterFields(
    config: Record<string, unknown>,
    patch: {
        dateFrom?: WidgetDateFromValue
        eventName?: string | null
    }
): ActivityEventsWidgetConfig {
    const base = parseActivityEventsWidgetConfig(config)

    return activityEventsWidgetConfigSchema.parse({
        ...base,
        dateRange: { date_from: patch.dateFrom ?? base.dateRange?.date_from ?? ACTIVITY_EVENTS_DEFAULT_DATE_FROM },
        // `in` (not ??) so an explicit null clears the filter — ?? would fall back to base
        eventName: 'eventName' in patch ? patch.eventName : base.eventName,
    })
}

export function buildActivityEventsWidgetConfig(
    formInput: ActivityEventsWidgetFormInput,
    baseConfig: ActivityEventsWidgetConfig
): ActivityEventsWidgetConfig {
    return activityEventsWidgetConfigSchema.parse({
        ...baseConfig,
        ...formInput,
    })
}

export function validateActivityEventsWidgetConfigInput(input: {
    limit: number
    filterTestAccounts: boolean
    baseConfig: ActivityEventsWidgetConfig
}):
    | { success: true; config: ActivityEventsWidgetConfig }
    | { success: false; fieldErrors: ActivityEventsWidgetFieldErrors } {
    const parsed = activityEventsWidgetFormSchema.safeParse({
        limit: input.limit,
        dateRange: { date_from: input.baseConfig.dateRange?.date_from ?? ACTIVITY_EVENTS_DEFAULT_DATE_FROM },
        filterTestAccounts: input.filterTestAccounts,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    const formInput: ActivityEventsWidgetFormInput = {
        limit: parsed.data.limit,
        dateRange: parsed.data.dateRange ?? null,
        filterTestAccounts: parsed.data.filterTestAccounts ?? null,
    }

    return {
        success: true,
        config: buildActivityEventsWidgetConfig(formInput, input.baseConfig),
    }
}

export function parseActivityEventsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ActivityEventsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = activityEventsWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = activityEventsWidgetFormSchema.safeParse({
        limit: (config.limit as number) ?? activityEventsConfigDefaults.limit ?? 0,
        dateRange: (config.dateRange as { date_from?: string | null } | undefined) ?? {
            date_from: ACTIVITY_EVENTS_DEFAULT_DATE_FROM,
        },
        filterTestAccounts: (config.filterTestAccounts as boolean) ?? false,
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
