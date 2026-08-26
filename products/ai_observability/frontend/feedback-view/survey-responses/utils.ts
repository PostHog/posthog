import { isString } from 'lib/utils/guards'
import { getSurveyResponseValue } from 'scenes/surveys/utils'

import { LLMTraceEvent } from '~/queries/schema/schema-general'
import { Survey, SurveyEventProperties, SurveyQuestion } from '~/types'

export interface GroupedResponse {
    submissionId: string
    surveyId: string
    responses: { questionIndex: number; question: SurveyQuestion; value: unknown }[]
    isComplete: boolean
}

/**
 * Reads the survey ID off a survey event, lowercased.
 *
 * `$survey_id` is captured by the instrumented app, so its case is whatever that app sent, while
 * survey IDs from the API are canonical lowercase. Match on the normalized form or an uppercase
 * ID looks like a survey that isn't in the project.
 */
export function getSurveyIdFromEvent(event: LLMTraceEvent): string | null {
    const surveyId = event.properties?.[SurveyEventProperties.SURVEY_ID]
    return isString(surveyId) ? surveyId.toLowerCase() : null
}

/**
 * Merges a trace's `survey sent` events into one response for each `$survey_submission_id`.
 *
 * A submission can arrive as several events, for example a thumbs rating and then a free-text
 * follow-up. Each event holds only the answers it collected, so the answers must be merged across
 * the submission's events instead of read from any single one.
 *
 * Callers must pass the events in ascending timestamp order. A question answered more than once
 * keeps its latest non-empty value, which matches how the responses API merges a submission with
 * `argMaxIf(answer, timestamp, isNotNull(answer))`.
 */
export function groupEventsBySubmission(events: LLMTraceEvent[], surveys: Record<string, Survey>): GroupedResponse[] {
    const submissionMap = new Map<string, GroupedResponse>()

    for (const event of events) {
        const props = event.properties || {}
        const surveyId = getSurveyIdFromEvent(event)
        const survey = surveyId ? surveys[surveyId] : null

        if (!surveyId || !survey) {
            continue
        }

        const submissionId = props[SurveyEventProperties.SURVEY_SUBMISSION_ID] || event.id

        if (!submissionMap.has(submissionId)) {
            submissionMap.set(submissionId, {
                submissionId,
                surveyId,
                responses: [],
                isComplete: props[SurveyEventProperties.SURVEY_COMPLETED] === true,
            })
        }

        const submission = submissionMap.get(submissionId)!

        for (let i = 0; i < survey.questions.length; i++) {
            const question = survey.questions[i]
            const value = getSurveyResponseValue(props, i, question.id)

            if (value != null && value !== '') {
                const existing = submission.responses.find((r) => r.questionIndex === i)
                if (existing) {
                    existing.value = value
                } else {
                    submission.responses.push({ questionIndex: i, question, value })
                }
            }
        }

        if (props[SurveyEventProperties.SURVEY_COMPLETED] === true) {
            submission.isComplete = true
        }
    }

    // Answers arrive in event order, so a submission whose later event answered an earlier
    // question would otherwise render its questions out of order.
    for (const submission of submissionMap.values()) {
        submission.responses.sort((a, b) => a.questionIndex - b.questionIndex)
    }

    return Array.from(submissionMap.values())
}

/**
 * Picks the `survey shown` events that deserve a "shown but received no response" card.
 *
 * A survey with a `survey sent` event on the same trace was answered, so its impression is not
 * worth a card. An instrumented app can also send `survey shown` more than once for one survey,
 * so only the first of each survives.
 */
export function selectUnansweredShownEvents(events: LLMTraceEvent[]): LLMTraceEvent[] {
    const answeredSurveyIds = new Set<string>()
    for (const event of events) {
        const surveyId = getSurveyIdFromEvent(event)
        if (event.event === 'survey sent' && surveyId) {
            answeredSurveyIds.add(surveyId)
        }
    }

    // A `survey shown` event without a readable `$survey_id` still renders, as an unnamed survey.
    // Keying those together collapses them into the single card they used to get.
    const shownBySurvey = new Map<string, LLMTraceEvent>()
    for (const event of events) {
        if (event.event !== 'survey shown') {
            continue
        }
        const surveyId = getSurveyIdFromEvent(event)
        if (surveyId && answeredSurveyIds.has(surveyId)) {
            continue
        }
        const key = surveyId ?? ''
        if (!shownBySurvey.has(key)) {
            shownBySurvey.set(key, event)
        }
    }

    return Array.from(shownBySurvey.values())
}
