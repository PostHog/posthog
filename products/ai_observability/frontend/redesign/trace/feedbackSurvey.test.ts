import { SurveyQuestionBranchingType, SurveyQuestionType, SurveyType } from '~/types'

import { buildFeedbackSurveyPayload, buildThumbSurveySnippet } from './feedbackSurvey'

describe('buildFeedbackSurveyPayload', () => {
    it('builds a live API survey with a thumbs question that useThumbSurvey can drive', () => {
        const payload = buildFeedbackSurveyPayload({
            name: '  Docs chatbot feedback ',
            followUpEnabled: false,
            followUpQuestion: 'What went wrong?',
        })

        expect(payload.name).toBe('Docs chatbot feedback')
        expect(payload.type).toBe(SurveyType.API)
        expect(payload.start_date).toEqual(expect.any(String))
        expect(payload.questions).toEqual([
            expect.objectContaining({
                type: SurveyQuestionType.Rating,
                display: 'emoji',
                scale: 2,
                skipSubmitButton: true,
                optional: false,
            }),
        ])
        expect(payload.questions?.[0]).not.toHaveProperty('branching')
    })

    it('adds a follow-up that only a thumbs down reaches', () => {
        const payload = buildFeedbackSurveyPayload({
            name: 'Agent feedback',
            followUpEnabled: true,
            followUpQuestion: ' What went wrong? ',
        })

        expect(payload.questions).toHaveLength(2)
        expect(payload.questions?.[0].branching).toEqual({
            type: SurveyQuestionBranchingType.ResponseBased,
            responseValues: { positive: SurveyQuestionBranchingType.End },
        })
        expect(payload.questions?.[1]).toEqual({
            type: SurveyQuestionType.Open,
            question: 'What went wrong?',
            optional: true,
        })
    })

    it('skips the follow-up when its question is blank', () => {
        const payload = buildFeedbackSurveyPayload({
            name: 'Agent feedback',
            followUpEnabled: true,
            followUpQuestion: ' ',
        })

        expect(payload.questions).toHaveLength(1)
        expect(payload.questions?.[0]).not.toHaveProperty('branching')
    })
})

describe('buildThumbSurveySnippet', () => {
    it('passes the survey id and the trace id to useThumbSurvey', () => {
        const snippet = buildThumbSurveySnippet('survey-123')

        expect(snippet).toContain("surveyId: 'survey-123'")
        expect(snippet).toContain('$ai_trace_id: traceId')
    })
})
