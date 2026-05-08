import { SurveyQuestionType } from '~/types'

import { getDefaultSurveyMessage, remapSurveyResponseProperties } from './surveyNotificationModalLogic'

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

    it('remaps copied survey response properties to the target survey questions by order', () => {
        const copiedInputs = {
            text: {
                value: "First: {event.properties['$survey_response_source-a']} second: {event.properties['$survey_response_source-b']}",
            },
            body: {
                value: {
                    '$survey_response_source-a': "{event.properties['$survey_response_source-a']}",
                    nested: ["{event.properties['$survey_response_source-b']}"],
                },
            },
        }

        expect(
            remapSurveyResponseProperties(copiedInputs, {
                id: 'target-survey',
                name: 'Target survey',
                enable_partial_responses: true,
                questions: [
                    { id: 'target-a', question: 'First?', type: SurveyQuestionType.Open },
                    { id: 'target-b', question: 'Second?', type: SurveyQuestionType.Open },
                ],
            })
        ).toEqual({
            text: {
                value: "First: {event.properties['$survey_response_target-a']} second: {event.properties['$survey_response_target-b']}",
            },
            body: {
                value: {
                    '$survey_response_target-a': "{event.properties['$survey_response_target-a']}",
                    nested: ["{event.properties['$survey_response_target-b']}"],
                },
            },
        })
    })

    it('removes copied survey response properties that do not have a target question', () => {
        const copiedInputs = {
            text: {
                value: "First: {event.properties['$survey_response_source-a']} extra: {event.properties['$survey_response_source-b']}",
            },
            body: {
                value: {
                    '$survey_response_source-a': "{event.properties['$survey_response_source-a']}",
                    '$survey_response_source-b': "{event.properties['$survey_response_source-b']}",
                },
            },
        }

        expect(
            remapSurveyResponseProperties(copiedInputs, {
                id: 'target-survey',
                name: 'Target survey',
                enable_partial_responses: true,
                questions: [{ id: 'target-a', question: 'First?', type: SurveyQuestionType.Open }],
            })
        ).toEqual({
            text: {
                value: "First: {event.properties['$survey_response_target-a']} extra: ",
            },
            body: {
                value: {
                    '$survey_response_target-a': "{event.properties['$survey_response_target-a']}",
                },
            },
        })
    })
})
