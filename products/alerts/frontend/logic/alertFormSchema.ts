import type { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { z } from 'zod'

import { dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils/objects'

import { AlertConditionType, ForecastConditionType } from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import type { AlertType } from '../types'
import type { AlertFormType } from './alertFormLogic'
import { forecastTargetDateError, forecastTargetValueError } from './forecastReach'
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
    // A band-deviation forecast scores the value against the forecast's own band, so there is no
    // threshold for the user to enter. A future-breach forecast still uses the bounds below.
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
                            .nullish(),
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

        // Save used to be the only thing that checked a target, so the user met the server's
        // message as a toast with no field marked, after a round trip.
        const forecast = (alert as AlertFormType).forecast_config
        if (forecast?.condition === ForecastConditionType.TARGET_BY_DATE) {
            const targetError = forecastTargetValueError(forecast.target)
            if (targetError) {
                ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['forecast_config'], message: targetError })
            }
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

/** What the form alone cannot tell us. `savedTargetDate` is the date already stored on the alert:
 *  one that was legitimate when it was saved must keep saving, or a target alert whose date has
 *  arrived can no longer be renamed or turned off. The server draws the same line. */
export interface AlertValidationContext {
    /** The forecast config already stored on the alert, when there is one. The server re-checks the
     *  target date whenever a request carries a forecast config at all, so the editor has to use the
     *  same trigger, or editing just the target sends an old date the server then rejects. */
    savedForecastConfig?: AlertFormType['forecast_config']
    insightInterval?: IntervalType | null
}

export function getAlertFormValidationErrors(
    alert: AlertFormType,
    context: AlertValidationContext = {}
): DeepPartialMap<AlertFormType, ValidationErrorType> {
    const errors: Record<string, ValidationErrorType> = {}

    const forecast = alert.forecast_config
    const forecastConfigWillBeSent = !objectsEqual(forecast ?? null, context.savedForecastConfig ?? null)
    if (
        forecast?.condition === ForecastConditionType.TARGET_BY_DATE &&
        forecast.target_date &&
        forecastConfigWillBeSent
    ) {
        const dateError = forecastTargetDateError(forecast.target_date, dayjs(), context.insightInterval)
        if (dateError) {
            errors.forecast_config = dateError
        }
    }

    const result = alertFormSchema.safeParse(alert)
    if (result.success) {
        return errors as DeepPartialMap<AlertFormType, ValidationErrorType>
    }

    for (const issue of result.error.issues) {
        const field = issue.path[0]
        if (typeof field === 'string' && errors[field] === undefined) {
            errors[field] = issue.message
        }
    }
    return errors as DeepPartialMap<AlertFormType, ValidationErrorType>
}
