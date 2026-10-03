import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { extractValidSurveyIds } from './feedbackViewLogic'

const surveyEvent = (surveyId: unknown): LLMTraceEvent => ({
    id: `event-${String(surveyId)}`,
    event: 'survey sent',
    properties: { $survey_id: surveyId },
    createdAt: '2024-01-01T00:00:00Z',
})

describe('feedbackViewLogic: extractValidSurveyIds', () => {
    const validId = '0199ed4a-5c03-0000-3220-df21df612e95'
    const otherValidId = '0199ed4a-5c03-0000-3220-df21df612e96'

    it('collects unique survey IDs', () => {
        expect(extractValidSurveyIds([surveyEvent(validId), surveyEvent(otherValidId), surveyEvent(validId)])).toEqual([
            validId,
            otherValidId,
        ])
    })

    it.each([
        ['a placeholder from a copied snippet', 'your-survey-id'],
        ['a survey name', 'AI response feedback'],
        ['a quoted UUID', `'${validId}'`],
        ['an empty string', ''],
        ['a missing property', undefined],
    ])('drops %s', (_description, surveyId) => {
        expect(extractValidSurveyIds([surveyEvent(surveyId)])).toEqual([])
        expect(extractValidSurveyIds([surveyEvent(surveyId), surveyEvent(validId)])).toEqual([validId])
    })

    it('normalizes case so the survey lookup matches', () => {
        expect(extractValidSurveyIds([surveyEvent(validId.toUpperCase())])).toEqual([validId])
    })

    it('returns nothing before the survey events load', () => {
        expect(extractValidSurveyIds(null)).toEqual([])
    })
})
