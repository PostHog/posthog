import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    experimentsWidgetConfigSchema,
    experimentsWidgetFormSchema,
    type ExperimentsWidgetConfig,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export const EXPERIMENTS_WIDGET_FORM_FIELD_NAMES = Object.keys(
    experimentsWidgetFormSchema.shape
) as (keyof typeof experimentsWidgetFormSchema.shape)[]

type ExperimentsListWidgetFormField = keyof z.infer<typeof experimentsWidgetFormSchema>

export type ExperimentsListWidgetFieldErrors = Partial<Record<ExperimentsListWidgetFormField, string>>

export type ExperimentsListWidgetStatus = NonNullable<ExperimentsWidgetConfig['status']>

export const EXPERIMENTS_WIDGET_STATUS_OPTIONS: { value: ExperimentsListWidgetStatus; label: string }[] = [
    { value: 'all', label: 'Any status' },
    { value: 'draft', label: 'Draft' },
    { value: 'running', label: 'Running' },
    { value: 'paused', label: 'Paused' },
    { value: 'stopped', label: 'Complete' },
]

const experimentsConfigDefaults = experimentsWidgetConfigSchema.parse({})

export function parseExperimentsListWidgetConfig(config: Record<string, unknown>): ExperimentsWidgetConfig {
    return parseWidgetConfig(experimentsWidgetConfigSchema, config)
}

/** Merge a partial status/creator change into an existing config, returning the full validated config. */
export function patchExperimentsListWidgetConfig(
    config: Record<string, unknown>,
    patch: { status?: ExperimentsListWidgetStatus; createdBy?: number | null }
): ExperimentsWidgetConfig {
    const parsed = parseExperimentsListWidgetConfig(config)
    return experimentsWidgetConfigSchema.parse({
        ...parsed,
        ...(patch.status !== undefined ? { status: patch.status } : {}),
        ...(patch.createdBy !== undefined ? { createdBy: patch.createdBy } : {}),
    })
}

export function validateExperimentsListWidgetConfigInput(input: {
    limit: number
    status: ExperimentsListWidgetStatus
    createdBy: number | null
}):
    | { success: true; config: ExperimentsWidgetConfig }
    | { success: false; fieldErrors: ExperimentsListWidgetFieldErrors } {
    const parsed = experimentsWidgetFormSchema.safeParse({
        limit: input.limit,
        status: input.status,
        createdBy: input.createdBy,
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return { success: true, config: experimentsWidgetConfigSchema.parse(parsed.data) }
}

export function parseExperimentsListWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ExperimentsListWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = experimentsWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = experimentsWidgetFormSchema.safeParse({
        limit: (config.limit as number) ?? experimentsConfigDefaults.limit ?? 0,
        status: (config.status as ExperimentsListWidgetStatus) ?? experimentsConfigDefaults.status ?? 'all',
        createdBy: (config.createdBy as number | null) ?? null,
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
