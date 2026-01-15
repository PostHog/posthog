import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { BatchExportConfiguration } from '~/types'

import type { batchExportBackfillModalLogicType } from './batchExportBackfillModalLogicType'
import { batchExportConfigurationLogic } from './batchExportConfigurationLogic'
import { dayOptions, intervalOffsetToDayAndHour } from './utils'

export interface BatchExportBackfillModalLogicProps {
    id: string
}

/**
 * Formats a date value for display in the calendar picker.
 */
export function formatDateForDisplay(value: Dayjs | null | undefined): Dayjs | null | undefined {
    if (!value) {
        return value
    }
    // replace the timezone with UTC as the calendar date picker doesn't play well with timezones
    return value.tz('UTC', true)
}

/**
 * Transforms a date when the user selects it in the calendar picker.
 * Converts to the appropriate timezone and sets hour/minute/second for day/week intervals.
 */
export function transformDateOnChange(
    date: Dayjs | null,
    interval: string | undefined,
    timezone: string,
    hourOffset: number | null
): Dayjs | null {
    if (!date) {
        return date
    }
    // replace the timezone with expected timezone
    let dateWithTz = date.tz(timezone, true)
    if (interval === 'day' || interval === 'week') {
        dateWithTz = dateWithTz
            .hour(hourOffset ?? 0)
            .minute(0)
            .second(0)
    }
    return dateWithTz
}

/**
 * Determines the calendar granularity based on the batch export interval.
 * Returns 'hour' for hour intervals, 'minute' for minute intervals, and 'day' otherwise.
 */
export function getCalendarGranularity(interval: string | undefined): 'hour' | 'minute' | 'day' {
    if (!interval) {
        return 'day'
    }
    if (interval === 'hour') {
        return 'hour'
    }
    if (interval.endsWith('minutes')) {
        return 'minute'
    }
    return 'day'
}

/**
 * Calculates the most recent valid interval boundary based on interval, timezone, and offset.
 * This ensures the end_at date aligns with the batch export's schedule.
 */
export function getMostRecentIntervalBoundary(
    interval: string | undefined,
    timezone: string,
    hourOffset: number | null,
    dayOfWeek: number | null
): Dayjs {
    const now = dayjs().tz(timezone)

    if (!interval) {
        return now.hour(0).minute(0).second(0).millisecond(0)
    }

    if (interval === 'day') {
        const hour = hourOffset ?? 0
        let boundary = now.hour(hour).minute(0).second(0).millisecond(0)
        // If we're before today's boundary, use yesterday's boundary
        if (boundary.isAfter(now)) {
            boundary = boundary.subtract(1, 'day')
        }
        return boundary
    }

    if (interval === 'week') {
        const hour = hourOffset ?? 0
        const day = dayOfWeek ?? 0

        // Find the most recent occurrence of this day of week at the specified hour
        let boundary = now.day(day).hour(hour).minute(0).second(0).millisecond(0)

        // If we're before this week's occurrence, use last week's occurrence
        if (boundary.isAfter(now)) {
            boundary = boundary.subtract(1, 'week')
        }
        return boundary
    }

    // if hourly or every 5 minutes, return the current hour
    return now.minute(0).second(0).millisecond(0)
}

export const batchExportBackfillModalLogic = kea<batchExportBackfillModalLogicType>([
    props({} as BatchExportBackfillModalLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'batchExportBackfillModalLogic', key]),
    connect((props: BatchExportBackfillModalLogicProps) => ({
        values: [
            batchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['batchExportConfig'],
        ],
    })),
    actions({
        openBackfillModal: true,
        closeBackfillModal: true,
        setEarliestBackfill: true,
        unsetEarliestBackfill: true,
    }),
    reducers({
        isBackfillModalOpen: [
            false,
            {
                openBackfillModal: () => true,
                closeBackfillModal: () => false,
            },
        ],
        isEarliestBackfill: [
            false,
            {
                setEarliestBackfill: () => true,
                unsetEarliestBackfill: () => false,
            },
        ],
    }),
    selectors({
        interval: [
            (s) => [s.batchExportConfig],
            (batchExportConfig: BatchExportConfiguration | null): string | undefined => batchExportConfig?.interval,
        ],
        timezone: [
            (s) => [s.batchExportConfig, teamLogic.selectors.timezone],
            (batchExportConfig: BatchExportConfiguration | null, teamTimezone: string): string => {
                // How timezones are handled:
                // - If the batch export's interval is day or week, we use the timezone from the batch export config.
                // - Otherwise, the timezone doesn't make any difference (and is set to UTC by default on the batch export)
                //   so we use the team/project's timezone when displaying the timezone in the UI.
                // Note: all dates sent to the backend are converted to UTC using toISOString(), so the timezone is purely
                // for use in the UI.
                const interval = batchExportConfig?.interval
                const useTeamTimezone = interval !== 'day' && interval !== 'week'
                return useTeamTimezone ? teamTimezone : (batchExportConfig?.timezone ?? 'UTC')
            },
        ],
        dayOfWeek: [
            (s) => [s.batchExportConfig],
            (batchExportConfig: BatchExportConfiguration | null): number | null => {
                const interval = batchExportConfig?.interval
                if (interval === 'day' || interval === 'week') {
                    const { day } = intervalOffsetToDayAndHour(batchExportConfig?.interval_offset ?? 0)
                    if (day < 0 || day > 6) {
                        throw new Error('Invalid day of week')
                    }
                    return day
                }
                return null
            },
        ],
        dayOfWeekName: [
            (s) => [s.batchExportConfig],
            (batchExportConfig: BatchExportConfiguration | null): string | null => {
                const interval = batchExportConfig?.interval
                if (interval === 'day' || interval === 'week') {
                    const { day } = intervalOffsetToDayAndHour(batchExportConfig?.interval_offset ?? 0)
                    if (day < 0 || day > 6) {
                        throw new Error('Invalid day of week')
                    }
                    return dayOptions[day].label
                }
                return null
            },
        ],
        hourOffset: [
            (s) => [s.batchExportConfig],
            (batchExportConfig: BatchExportConfiguration | null): number | null => {
                const interval = batchExportConfig?.interval
                if (interval === 'day' || interval === 'week') {
                    const { hour } = intervalOffsetToDayAndHour(batchExportConfig?.interval_offset ?? 0)
                    if (hour < 0 || hour > 23) {
                        throw new Error('Invalid hour offset')
                    }
                    return hour
                }
                return null
            },
        ],
        defaultEndAt: [
            (s) => [s.interval, s.timezone, s.hourOffset, s.dayOfWeek],
            (
                interval: string | undefined,
                timezone: string,
                hourOffset: number | null,
                dayOfWeek: number | null
            ): Dayjs => {
                return getMostRecentIntervalBoundary(interval, timezone, hourOffset, dayOfWeek)
            },
        ],
    }),
    forms(({ props, actions, values }) => ({
        backfillForm: {
            defaults: {
                start_at: undefined,
                end_at: getMostRecentIntervalBoundary(
                    values.interval,
                    values.timezone,
                    values.hourOffset,
                    values.dayOfWeek
                ),
                earliest_backfill: false,
            } as {
                start_at?: Dayjs
                end_at?: Dayjs
                earliest_backfill: boolean
            },

            errors: ({ start_at, end_at, earliest_backfill }) => {
                const errors: {
                    start_at?: string
                    end_at?: string
                    earliest_backfill?: string
                } = {}

                // Required field validation
                if (!start_at && !earliest_backfill) {
                    errors.start_at = 'Start date is required'
                }

                if (!end_at) {
                    errors.end_at = 'End date is required'
                }

                // Only validate format/business rules if fields are present
                if (start_at && !errors.start_at) {
                    // Validate minute intervals (e.g., 5-minute exports require multiples of 5)
                    if (values.batchExportConfig && values.batchExportConfig.interval.endsWith('minutes')) {
                        // TODO: Make this generic for all minute frequencies.
                        // Currently, only 5 minute batch exports are supported.
                        if (start_at.minute() !== undefined && !(start_at.minute() % 5 === 0)) {
                            errors.start_at = 'Start time must be a multiple of 5 minutes for 5-minute batch exports'
                        }
                    }
                    // validate that weekly exports are on a valid day of the week
                    if (values.batchExportConfig && values.batchExportConfig.interval === 'week') {
                        if (start_at.day() !== values.dayOfWeek) {
                            errors.start_at = `Start date must be on a valid day of the week (${values.dayOfWeekName}) for weekly batch exports`
                        }
                    }
                }

                if (end_at && !errors.end_at) {
                    // Validate minute intervals for end date
                    if (values.batchExportConfig && values.batchExportConfig.interval.endsWith('minutes')) {
                        // TODO: Make this generic for all minute frequencies.
                        // Currently, only 5 minute batch exports are supported.
                        if (end_at.minute() !== undefined && !(end_at.minute() % 5 === 0)) {
                            errors.end_at = 'End time must be a multiple of 5 minutes for 5-minute batch exports'
                        }
                    }

                    // Validate that weekly exports are on a valid day of the week
                    if (values.batchExportConfig && values.batchExportConfig.interval === 'week') {
                        if (end_at.day() !== values.dayOfWeek) {
                            errors.end_at = 'End date must be on a valid day of the week for weekly batch exports'
                        }
                    }

                    // Validate that end date is not in the future
                    const upperBound = dayjs().tz(teamLogic.values.timezone)
                    if (end_at > upperBound) {
                        errors.end_at = 'End date cannot be in the future'
                    }

                    if (start_at && end_at < start_at) {
                        errors.end_at = 'End date must be after start date'
                    }
                }

                return errors
            },

            submit: async ({ start_at, end_at, earliest_backfill }) => {
                await api.batchExports
                    .createBackfill(props.id, {
                        start_at: earliest_backfill ? null : (start_at?.toISOString() ?? null),
                        end_at: end_at?.toISOString() ?? null,
                    })
                    .catch((e) => {
                        if (e.detail) {
                            actions.setBackfillFormManualErrors({
                                [e.attr ?? 'end_at']: e.detail,
                            })
                        } else {
                            lemonToast.error('Unknown error occurred')
                        }

                        throw e
                    })

                actions.closeBackfillModal()
                return
            },
        },
    })),
])
