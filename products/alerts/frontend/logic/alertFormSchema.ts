import type { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { z } from 'zod'

import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'

import { AlertConditionType, ForecastConditionType } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import type { AlertType } from '../types'
import type { AlertFormType } from './alertFormLogic'
import { cadenceFinerThanInsightInterval } from './alertIntervalHelpers'
import {
    forecastTargetDateError,
    forecastTargetIntervalError,
    forecastTargetReachError,
    forecastTargetValueError,
} from './forecastReach'
import { quietHoursFormError } from './scheduleRestrictionValidation'

export const THRESHOLD_BOUNDS_FORM_ERROR = 'Enter at least one threshold (less than or more than)'
export const INVERTED_THRESHOLD_BOUNDS_FORM_ERROR = 'The “Less than” value must be lower than the “More than” value'

const NAME_REQUIRED_MESSAGE = 'You need to give your alert a name'

function isFiniteThresholdBound(value: number | null | undefined): value is number {
    return value != null && Number.isFinite(value)
}

/** Whether the pair of bounds is impossible to satisfy: every value sits outside one of them, so
 * the comparator reports a breach on the very first point. */
export function hasInvertedThresholdBounds(
    bounds: { lower?: number | null; upper?: number | null } | null | undefined
): boolean {
    return isFiniteThresholdBound(bounds?.lower) && isFiniteThresholdBound(bounds?.upper) && bounds.lower > bounds.upper
}

export function thresholdAlertHasBounds(alert: AlertFormType | AlertType): boolean {
    if (alert.detector_config) {
        return true
    }
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
        const forecast = (alert as AlertFormType).forecast_config
        // Only the threshold and predicted-breach paths show the bounds, so both bound rules stop
        // here for a target alert. A stale bound it never reads must not block the save with an
        // error no visible field can show.
        const usesThresholdBounds = !forecast || forecast.condition === ForecastConditionType.FUTURE_BREACH
        if (!alert.detector_config && usesThresholdBounds && hasInvertedThresholdBounds(bounds)) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['threshold'],
                message: INVERTED_THRESHOLD_BOUNDS_FORM_ERROR,
            })
        }

        if (forecast?.condition === ForecastConditionType.TARGET_BY_DATE) {
            const targetError = forecastTargetValueError(forecast.target)
            if (targetError) {
                ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['forecast_config'], message: targetError })
            }
        }

        const hasNegativeRelativeBound =
            usesThresholdBounds &&
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

export interface AlertValidationContext {
    savedTargetDate?: string
    savedEnabled?: boolean
    insightInterval?: IntervalType | null
    projectTimezone?: string
}

export function getAlertFormValidationErrors(
    alert: AlertFormType,
    context: AlertValidationContext = {}
): DeepPartialMap<AlertFormType, ValidationErrorType> {
    const errors: Record<string, ValidationErrorType> = {}

    const forecast = alert.forecast_config
    if (forecast?.condition === ForecastConditionType.TARGET_BY_DATE) {
        const today = context.projectTimezone ? dayjsNowInTimezone(context.projectTimezone) : dayjs()
        // An unchanged date keeps its past-date pass, matching the server, so an expired alert can
        // still be renamed or turned off. Turning one back on gives up that pass, also matching the
        // server: the scheduler expires it again on its next sweep, so the enable never persists.
        // How far the date reaches is checked either way, because regrouping the insight to a finer
        // interval can push a saved date over the point limit.
        const turningBackOn = alert.enabled === true && context.savedEnabled === false
        const dateError =
            forecast.target_date === context.savedTargetDate && !turningBackOn
                ? forecastTargetReachError(forecast.target_date, today, context.insightInterval)
                : forecastTargetDateError(forecast.target_date, today, context.insightInterval)
        // The interval comes first, the way the server validates it: on an hourly insight no date
        // works, so naming the date would send the reader after the wrong setting.
        const forecastError = forecastTargetIntervalError(context.insightInterval) ?? dateError
        if (forecastError) {
            errors.forecast_config = forecastError
        }
    }

    if (forecast && cadenceFinerThanInsightInterval(alert.calculation_interval, context.insightInterval)) {
        errors.calculation_interval = `A forecast alert cannot run more often than the insight's ${
            context.insightInterval ?? 'day'
        } interval. Choose a slower cadence.`
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
