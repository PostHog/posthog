import { z } from 'zod'

import {
    sessionReplayWidgetConfigSchema,
    sessionReplayWidgetFormSchema,
    type SessionReplayWidgetConfig,
} from '../../widget_types/configSchemas'
import {
    buildWidgetConfigFromForm,
    parseWidgetConfig,
    parseWidgetConfigApiError,
    type WidgetListFormInput,
    validateWidgetConfigInput as validateWidgetConfigInputShared,
} from '../widgetConfigValidation'

type SessionReplayWidgetFormField = keyof z.infer<typeof sessionReplayWidgetFormSchema>

export type SessionReplayWidgetFieldErrors = Partial<Record<SessionReplayWidgetFormField, string>>

export function parseSessionReplayWidgetConfig(config: Record<string, unknown>): SessionReplayWidgetConfig {
    return parseWidgetConfig(sessionReplayWidgetConfigSchema, config)
}

export function buildSessionReplayWidgetConfig(
    formInput: WidgetListFormInput,
    baseConfig: SessionReplayWidgetConfig
): SessionReplayWidgetConfig {
    return buildWidgetConfigFromForm(sessionReplayWidgetConfigSchema, formInput, baseConfig)
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
    return validateWidgetConfigInputShared({
        formSchema: sessionReplayWidgetFormSchema,
        buildConfig: buildSessionReplayWidgetConfig,
        input,
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
        defaultOrderBy: 'start_time',
    })
}
