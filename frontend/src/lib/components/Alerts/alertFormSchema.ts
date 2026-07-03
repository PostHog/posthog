import type { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { z } from 'zod'

import { ForecastConditionType } from '~/queries/schema/schema-general'

import type { AlertFormType } from './alertFormLogic'
import { quietHoursFormError } from './scheduleRestrictionValidation'
import type { AlertType } from './types'

export const THRESHOLD_BOUNDS_FORM_ERROR = 'Enter at least one threshold (less than or more than)'

const NAME_REQUIRED_MESSAGE = 'You need to give your alert a name'

function isFiniteThresholdBound(value: number | string | null | undefined): boolean {
    if (value == null || value === '') {
        return false
    }
    return !Number.isNaN(Number(value))
}

export function thresholdAlertHasBounds(alert: AlertFormType | AlertType): boolean {
    if (alert.detector_config) {
        return true
    }
    // A band-deviation forecast alert scores the actual against the forecast's own uncertainty band —
    // there's no user-set threshold to enter. A future-breach forecast still evaluates against the
    // threshold bounds below.
    if (alert.forecast_config && alert.forecast_config.condition !== ForecastConditionType.FUTURE_BREACH) {
        return true
    }
    const bounds = alert.threshold?.configuration?.bounds
    if (!bounds) {
        return false
    }
    const { lower, upper } = bounds
    return isFiniteThresholdBound(lower) || isFiniteThresholdBound(upper)
}

const alertFormSchema = z
    .object({
        name: z.string(),
        detector_config: z.unknown().nullable(),
        threshold: z
            .object({
                configuration: z
                    .object({
                        bounds: z
                            .object({
                                lower: z.union([z.number(), z.string()]).nullish(),
                                upper: z.union([z.number(), z.string()]).nullish(),
                            })
                            .optional(),
                    })
                    .optional(),
            })
            .optional(),
        schedule_restriction: z.custom<AlertFormType['schedule_restriction']>().nullable().optional(),
    })
    .passthrough()
    .superRefine((alert, ctx) => {
        if (!alert.name) {
            ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['name'], message: NAME_REQUIRED_MESSAGE })
        }

        const scheduleError = quietHoursFormError(alert.schedule_restriction)
        if (scheduleError) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['schedule_restriction'],
                message: scheduleError,
            })
        }

        if (!thresholdAlertHasBounds(alert as AlertFormType)) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['threshold'],
                message: THRESHOLD_BOUNDS_FORM_ERROR,
            })
        }
    })

export function getAlertFormValidationErrors(alert: AlertFormType): DeepPartialMap<AlertFormType, ValidationErrorType> {
    const result = alertFormSchema.safeParse(alert)
    if (result.success) {
        return {}
    }

    const errors: Record<string, ValidationErrorType> = {}
    for (const issue of result.error.issues) {
        const field = issue.path[0]
        if (typeof field === 'string' && errors[field] === undefined) {
            errors[field] = issue.message
        }
    }
    return errors as DeepPartialMap<AlertFormType, ValidationErrorType>
}
