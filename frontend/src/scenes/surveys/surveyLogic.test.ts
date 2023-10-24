import { initKeaTests } from '~/test/init'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { Survey, SurveyQuestionType, SurveyType } from '~/types'

const SURVEY: Survey = {
    id: '018b22a3-09b1-0000-2f5b-1bd8352ceec9',
    name: 'Multiple Choice survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.MultipleChoice,
            choices: ['Tutorials', 'Customer case studies', 'Product announcements'],
            question: 'Which types of content would you like to see more of?',
            description: '',
        },
    ],
    conditions: null,
    appearance: {
        position: 'right',
        whiteLabel: false,
        borderColor: '#c9c6c6',
        placeholder: '',
        backgroundColor: '#eeeded',
        submitButtonText: 'Submit',
        ratingButtonColor: 'white',
        submitButtonColor: 'black',
        thankYouMessageHeader: 'Thank you for your feedback!',
        displayThankYouMessage: true,
        ratingButtonActiveColor: 'black',
    },
    created_at: '2023-10-12T06:46:32.113745Z',
    created_by: {
        id: 1,
        uuid: '018aa8a6-10e8-0000-dba2-0e956f7bae38',
        distinct_id: 'TGqg9Cn4jLkj9X87oXni9ZPBD6VbOxMtGV1GfJeB5LO',
        first_name: 'test',
        email: 'test@posthog.com',
        is_email_verified: false,
    },
    start_date: '2023-10-12T06:46:34.482000Z',
    end_date: null,
    archived: false,
    targeting_flag_filters: undefined,
}

describe('survey logic', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = surveyLogic({ id: 'new' })
        logic.mount()

        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { results: [] }],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
            post: {
                '/api/projects/:team/query/': () => [
                    200,
                    {
                        results: [
                            [336, '"Tutorials"'],
                            [312, '"Customer case studies"'],
                        ],
                    },
                ],
            },
        })
    })

    describe('main', () => {
        it('post processes return values', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSurveyMultipleChoiceResults({ questionIndex: 0 })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    surveyMultipleChoiceResults: {
                        0: {
                            labels: ['Tutorials', 'Customer case studies', 'Product announcements'],
                            data: [336, 312, 0],
                        },
                    },
                })
        })
    })
})
