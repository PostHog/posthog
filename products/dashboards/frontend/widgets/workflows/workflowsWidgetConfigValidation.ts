import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    workflowsWidgetConfigSchema,
    workflowsWidgetFormSchema,
    type WorkflowsWidgetConfig,
} from '../../generated/widget-configs.zod'
import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export type WorkflowsWidgetStatus = NonNullable<WorkflowsWidgetConfig['status']>
export type WorkflowsWidgetType = NonNullable<WorkflowsWidgetConfig['workflowType']>
type WorkflowsWidgetFormField = keyof z.infer<typeof workflowsWidgetFormSchema>
export type WorkflowsWidgetFieldErrors = Partial<Record<WorkflowsWidgetFormField, string>>

export const WORKFLOWS_WIDGET_DEFAULT_DATE_FROM: WidgetDateFromValue = '-7d'

export const WORKFLOWS_WIDGET_STATUS_OPTIONS: { value: WorkflowsWidgetStatus; label: string }[] = [
    { value: 'all', label: 'Any status' },
    { value: 'active', label: 'Active' },
    { value: 'draft', label: 'Draft' },
    { value: 'archived', label: 'Archived' },
]

export const WORKFLOWS_WIDGET_TYPE_OPTIONS: { value: WorkflowsWidgetType; label: string }[] = [
    { value: 'all', label: 'Any type' },
    { value: 'messaging', label: 'Messaging' },
    { value: 'automation', label: 'Automation' },
    { value: 'broadcast', label: 'Broadcast' },
    { value: 'loop', label: 'Loop' },
]

export function parseWorkflowsWidgetConfig(config: Record<string, unknown>): WorkflowsWidgetConfig {
    return parseWidgetConfig(workflowsWidgetConfigSchema, config)
}

/** Merge a tile-bar filter change into an existing config, returning the full validated config. */
export function patchWorkflowsWidgetFilterFields(
    config: Record<string, unknown>,
    patch: { status?: WorkflowsWidgetStatus; workflowType?: WorkflowsWidgetType; dateFrom?: WidgetDateFromValue }
): WorkflowsWidgetConfig {
    const base = parseWorkflowsWidgetConfig(config)
    return workflowsWidgetConfigSchema.parse({
        ...base,
        status: patch.status ?? base.status,
        workflowType: patch.workflowType ?? base.workflowType,
        dateRange: patch.dateFrom ? { date_from: patch.dateFrom } : base.dateRange,
    })
}

export function parseWorkflowsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): WorkflowsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }
    const parsed = workflowsWidgetConfigSchema.safeParse(config)
    return parsed.success ? null : fieldErrorsFromZodError(parsed.error)
}
