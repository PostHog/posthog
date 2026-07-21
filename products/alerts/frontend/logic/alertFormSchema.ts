import type { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { z } from 'zod'

import { AlertConditionType } from '~/queries/schema/schema-general'

import type { AlertType } from '../types'
import type { AlertFormType } from './alertFormLogic'
import { quietHoursFormError } from './scheduleRestrictionValidation'

export const THRESHOLD_BOUNDS_FORM_ERROR = 'Enter at least one threshold (less than or more than)'

const NAME_REQUIRED_MESSAGE = 'You need to give your alert a name'

function isFiniteThresholdBound(value: number | null | undefined): value is number {
    return value != null && Number.isFinite(value)
}

export function thresholdAlertHasBounds(alert: AlertFormType | AlertType): boolean {
    if (alert.detector_config) {
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
        condition: z.object({ type: z.nativeEnum(AlertConditionType) }),
        threshold: z
            .object({
                configuration: z
                    .object({
                        bounds: z
                            .object({
                                lower: z.number().finite().nullish(),
                                upper: z.number().finite().nullish(),
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

        const bounds = alert.threshold?.configuration?.bounds
        if (
            !alert.detector_config &&
            isFiniteThresholdBound(bounds?.lower) &&
            isFiniteThresholdBound(bounds?.upper) &&
            bounds.lower > bounds.upper
        ) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['threshold'],
                message: 'The “Less than” value must be lower than the “More than” value',
            })
        }

        const hasNegativeRelativeBound =
            alert.condition.type !== AlertConditionType.ABSOLUTE_VALUE &&
            [bounds?.lower, bounds?.upper].some((value) => isFiniteThresholdBound(value) && value < 0)
        if (hasNegativeRelativeBound) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['threshold'],
                message: 'Enter zero or a positive change value',
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
