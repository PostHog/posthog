import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    experimentResultsWidgetConfigSchema,
    experimentResultsWidgetFormSchema,
    type ExperimentResultsWidgetConfig,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

type ExperimentResultsWidgetFormField = keyof z.infer<typeof experimentResultsWidgetFormSchema>

export type ExperimentResultsWidgetFieldErrors = Partial<Record<ExperimentResultsWidgetFormField, string>>

export function parseExperimentResultsWidgetConfig(config: Record<string, unknown>): ExperimentResultsWidgetConfig {
    return parseWidgetConfig(experimentResultsWidgetConfigSchema, config)
}

/** Set the selected experiment on an existing config, returning the full validated config. */
export function patchExperimentResultsWidgetConfig(
    config: Record<string, unknown>,
    experimentId: number | null
): ExperimentResultsWidgetConfig {
    const parsed = parseExperimentResultsWidgetConfig(config)
    return experimentResultsWidgetConfigSchema.parse({ ...parsed, experimentId })
}

export function validateExperimentResultsWidgetConfigInput(input: {
    experimentId: number | null
}):
    | { success: true; config: ExperimentResultsWidgetConfig }
    | { success: false; fieldErrors: ExperimentResultsWidgetFieldErrors } {
    const parsed = experimentResultsWidgetFormSchema.safeParse({ experimentId: input.experimentId })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return { success: true, config: experimentResultsWidgetConfigSchema.parse(parsed.data) }
}

export function parseExperimentResultsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ExperimentResultsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = experimentResultsWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
