import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    canvasAppWidgetConfigSchema,
    canvasAppWidgetFormSchema,
    type CanvasAppWidgetConfig,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

type CanvasAppWidgetFormField = keyof z.infer<typeof canvasAppWidgetFormSchema>

export type CanvasAppWidgetFieldErrors = Partial<Record<CanvasAppWidgetFormField, string>>

export function parseCanvasAppWidgetConfig(config: Record<string, unknown>): CanvasAppWidgetConfig {
    return parseWidgetConfig(canvasAppWidgetConfigSchema, config)
}

/** Set the selected canvas on an existing config, returning the full validated config. */
export function patchCanvasAppWidgetConfig(
    config: Record<string, unknown>,
    canvasId: string | null
): CanvasAppWidgetConfig {
    const parsed = parseCanvasAppWidgetConfig(config)
    return canvasAppWidgetConfigSchema.parse({ ...parsed, canvasId })
}

export function validateCanvasAppWidgetConfigInput(input: {
    canvasId: string | null
}): { success: true; config: CanvasAppWidgetConfig } | { success: false; fieldErrors: CanvasAppWidgetFieldErrors } {
    const parsed = canvasAppWidgetFormSchema.safeParse({ canvasId: input.canvasId })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return { success: true, config: canvasAppWidgetConfigSchema.parse(parsed.data) }
}

export function parseCanvasAppWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): CanvasAppWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = canvasAppWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
