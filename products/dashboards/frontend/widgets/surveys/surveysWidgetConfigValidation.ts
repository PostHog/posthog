import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    surveyResultsWidgetConfigSchema,
    surveyResultsWidgetFormSchema,
    type SurveyResultsWidgetConfig,
} from '../../generated/widget-configs.zod'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

/** The "All time" date-range option: stored as no date range so the backend uses the survey's start/end. */
export const SURVEY_DATE_ALL_TIME = 'all' as const
export type SurveyWidgetDateFrom = WidgetDateFromValue | typeof SURVEY_DATE_ALL_TIME

export const SURVEY_RESULTS_WIDGET_DATE_RANGE_OPTIONS: { value: SurveyWidgetDateFrom; label: string }[] = [
    { value: SURVEY_DATE_ALL_TIME, label: 'All time' },
    ...WIDGET_DATE_RANGE_SELECT_OPTIONS,
]

type SurveyResultsWidgetFormField = keyof z.infer<typeof surveyResultsWidgetFormSchema>

export type SurveyResultsWidgetFieldErrors = Partial<Record<SurveyResultsWidgetFormField, string>>

const surveyResultsConfigDefaults = surveyResultsWidgetConfigSchema.parse({})

export function parseSurveyResultsWidgetConfig(config: Record<string, unknown>): SurveyResultsWidgetConfig {
    return parseWidgetConfig(surveyResultsWidgetConfigSchema, config)
}

export function dateFromValueForConfig(config: SurveyResultsWidgetConfig): SurveyWidgetDateFrom {
    return (config.dateRange?.date_from as WidgetDateFromValue | undefined) ?? SURVEY_DATE_ALL_TIME
}

function dateRangeForSelection(dateFrom: SurveyWidgetDateFrom): { date_from: WidgetDateFromValue } | null {
    return dateFrom === SURVEY_DATE_ALL_TIME ? null : { date_from: dateFrom }
}

export function patchSurveyResultsWidgetConfig(
    config: Record<string, unknown>,
    surveyId: string | null
): SurveyResultsWidgetConfig {
    const parsed = parseSurveyResultsWidgetConfig(config)
    return surveyResultsWidgetConfigSchema.parse({ ...parsed, surveyId })
}

export function validateSurveyResultsWidgetConfigInput(input: {
    surveyId: string | null
    limit: number
    dateFrom: SurveyWidgetDateFrom
    baseConfig: SurveyResultsWidgetConfig
}):
    | { success: true; config: SurveyResultsWidgetConfig }
    | { success: false; fieldErrors: SurveyResultsWidgetFieldErrors } {
    const parsed = surveyResultsWidgetFormSchema.safeParse({
        surveyId: input.surveyId,
        limit: input.limit,
        dateRange: dateRangeForSelection(input.dateFrom),
    })

    if (!parsed.success) {
        return { success: false, fieldErrors: fieldErrorsFromZodError(parsed.error) }
    }

    return {
        success: true,
        config: surveyResultsWidgetConfigSchema.parse({ ...input.baseConfig, ...parsed.data }),
    }
}

export function parseSurveyResultsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): SurveyResultsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }

    const parsedConfig = surveyResultsWidgetConfigSchema.safeParse(config)
    if (parsedConfig.success) {
        return null
    }

    const parsedForm = surveyResultsWidgetFormSchema.safeParse({
        surveyId: (config.surveyId as string | null) ?? null,
        limit: (config.limit as number) ?? surveyResultsConfigDefaults.limit ?? 0,
        dateRange: (config.dateRange as { date_from?: string | null } | undefined) ?? null,
    })
    if (!parsedForm.success) {
        return fieldErrorsFromZodError(parsedForm.error)
    }

    return fieldErrorsFromZodError(parsedConfig.error)
}
