import { dayjs } from 'lib/dayjs'

import type { Survey } from '~/types'

export function buildSurveyResumeUpdatePayload(scheduledStartDatetime?: string | null): Partial<Survey> {
    if (scheduledStartDatetime) {
        return { scheduled_start_datetime: scheduledStartDatetime }
    }

    // Resume immediately and clear any existing scheduled resume.
    return { end_date: null, scheduled_start_datetime: null }
}

export function buildSurveyStartUpdatePayload(
    scheduledStartDatetime?: string | null,
    nowIso: string = dayjs().toISOString()
): Partial<Survey> {
    if (scheduledStartDatetime) {
        return { scheduled_start_datetime: scheduledStartDatetime }
    }

    return { start_date: nowIso }
}

export function buildSurveyStopUpdatePayload(
    scheduledEndDatetime?: string | null,
    nowIso: string = dayjs().toISOString()
): Partial<Survey> {
    if (scheduledEndDatetime) {
        return { scheduled_end_datetime: scheduledEndDatetime }
    }

    return { end_date: nowIso }
}
