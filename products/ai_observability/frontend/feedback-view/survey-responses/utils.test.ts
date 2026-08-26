import { LLMTraceEvent } from '~/queries/schema/schema-general'
import { Survey, SurveyQuestionType } from '~/types'

import { groupEventsBySubmission, selectUnansweredShownEvents } from './utils'

const SURVEY_ID = '0199ed4a-5c03-0000-3220-df21df612e95'

const surveys: Record<string, Survey> = {
    [SURVEY_ID]: {
        id: SURVEY_ID,
        name: 'AI response feedback',
        questions: [
            { id: 'q1', type: SurveyQuestionType.Rating, question: 'Was this helpful?' },
            { id: 'q2', type: SurveyQuestionType.Open, question: 'Tell us more' },
        ],
    } as unknown as Survey,
}

const sentEvent = (id: string, properties: Record<string, unknown>): LLMTraceEvent => ({
    id,
    event: 'survey sent',
    createdAt: '2024-01-01T00:00:00Z',
    properties: { $survey_id: SURVEY_ID, ...properties },
})

const shownEvent = (id: string): LLMTraceEvent => ({
    id,
    event: 'survey shown',
    createdAt: '2024-01-01T00:00:00Z',
    properties: { $survey_id: SURVEY_ID },
})

describe('feedback view survey response utils', () => {
    describe('groupEventsBySubmission', () => {
        it('merges answers across a submission split over several events', () => {
            const grouped = groupEventsBySubmission(
                [
                    sentEvent('e1', {
                        $survey_submission_id: 's1',
                        $survey_response_q1: 2,
                        $survey_completed: false,
                    }),
                    sentEvent('e2', {
                        $survey_submission_id: 's1',
                        $survey_response_q2: 'it invented a hedgehog',
                        $survey_completed: true,
                    }),
                ],
                surveys
            )

            expect(grouped).toHaveLength(1)
            expect(grouped[0].isComplete).toBe(true)
            expect(grouped[0].responses.map((r) => [r.questionIndex, r.value])).toEqual([
                [0, 2],
                [1, 'it invented a hedgehog'],
            ])
        })

        it('keeps the latest answer when a question is answered twice', () => {
            const grouped = groupEventsBySubmission(
                [
                    sentEvent('e1', { $survey_submission_id: 's1', $survey_response_q1: 1 }),
                    sentEvent('e2', { $survey_submission_id: 's1', $survey_response_q1: 2, $survey_completed: true }),
                ],
                surveys
            )

            expect(grouped[0].responses).toEqual([expect.objectContaining({ questionIndex: 0, value: 2 })])
        })

        it('keeps events without a submission ID as separate responses', () => {
            const grouped = groupEventsBySubmission(
                [
                    sentEvent('e1', { $survey_response_q1: 1, $survey_completed: true }),
                    sentEvent('e2', { $survey_response_q1: 2, $survey_completed: true }),
                ],
                surveys
            )

            expect(grouped).toHaveLength(2)
        })
    })

    describe('selectUnansweredShownEvents', () => {
        it('drops the impression for a survey that was answered', () => {
            const kept = selectUnansweredShownEvents([
                shownEvent('e1'),
                sentEvent('e2', { $survey_response_q1: 1, $survey_completed: true }),
            ])

            expect(kept).toEqual([])
        })

        it('collapses duplicate impressions for one survey', () => {
            const kept = selectUnansweredShownEvents([shownEvent('e1'), shownEvent('e2')])

            expect(kept.map((e) => e.id)).toEqual(['e1'])
        })
    })
})
