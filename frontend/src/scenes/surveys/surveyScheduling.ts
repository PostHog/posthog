import type { Survey } from '~/types'

export function buildSurveyResumeUpdatePayload(scheduledStartDatetime?: string | null): Partial<Survey> {
    if (scheduledStartDatetime) {
        return { scheduled_start_datetime: scheduledStartDatetime }
    }

    // Resume immediately and clear any existing scheduled resume.
    return { end_date: null, scheduled_start_datetime: null }
}
