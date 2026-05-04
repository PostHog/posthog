import { SurveyQuestionType } from '~/types'

import { getDefaultSurveyMessage } from './surveyNotificationModalLogic'

describe('surveyNotificationModalLogic', () => {
    it('includes survey status text in the default notification message', () => {
        expect(
            getDefaultSurveyMessage([
                {
                    id: 'question-1',
                    question: 'What can we improve?',
                    type: SurveyQuestionType.Open,
                },
            ])
        ).toEqual(`*Survey update on {event.properties['$survey_name']}*
{event.event == 'survey dismissed' ? (event.properties['$survey_partially_completed'] ? 'Dismissed after a partial response' : 'Dismissed before completion') : 'Completed response'}
{person.name} · {person.properties.email}

*Responses*
- What can we improve?: {event.properties['$survey_response_question-1']}`)
    })
})
