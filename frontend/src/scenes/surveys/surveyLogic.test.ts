import { expectLogic } from 'kea-test-utils'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey, SurveyQuestionType, SurveyType } from '~/types'

const MULTIPLE_CHOICE_SURVEY: Survey = {
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
            choices: ['Tutorials', 'Customer case studies', 'Product announcements', 'Other'],
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

const SINGLE_CHOICE_SURVEY: Survey = {
    id: '118b22a3-09b1-0000-2f5b-1bd8352ceec9',
    name: 'Single Choice survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.SingleChoice,
            choices: ['Yes', 'No'],
            question: 'Would you like us to continue this feature?',
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

const MULTIPLE_CHOICE_SURVEY_WITH_OPEN_CHOICE: Survey = {
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
            choices: ['Tutorials', 'Customer case studies', 'Product announcements', 'Other'],
            question: 'Which types of content would you like to see more of?',
            description: '',
            hasOpenChoice: true,
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

const SINGLE_CHOICE_SURVEY_WITH_OPEN_CHOICE: Survey = {
    id: '118b22a3-09b1-0000-2f5b-1bd8352ceec9',
    name: 'Single Choice survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.SingleChoice,
            choices: ['Yes', 'No', 'Maybe (explain)'],
            question: 'Would you like us to continue this feature?',
            description: '',
            hasOpenChoice: true,
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

describe('multiple choice survey logic', () => {
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
                            [20, '"Other"'],
                        ],
                    },
                ],
            },
        })
    })

    describe('main', () => {
        it('post processes return values', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSurveyMultipleChoiceResults({ questionIndex: 0 })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    surveyMultipleChoiceResults: {
                        0: {
                            labels: ['Tutorials', 'Customer case studies', 'Other', 'Product announcements'],
                            data: [336, 312, 20, 0],
                        },
                    },
                })
        })
    })
})

describe('single choice survey logic', () => {
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
                            ['"Yes"', 101],
                            ['"No"', 1],
                        ],
                    },
                ],
            },
        })
    })

    describe('main', () => {
        it('post processes return values', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SINGLE_CHOICE_SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSurveySingleChoiceResults({ questionIndex: 1 })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    surveySingleChoiceResults: {
                        1: {
                            labels: ['"Yes"', '"No"'],
                            data: [101, 1],
                            total: 102,
                        },
                    },
                })
        })
    })
})

describe('multiple choice survey with open choice logic', () => {
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
                            [20, '"Other choice"'],
                        ],
                    },
                ],
            },
        })
    })

    describe('main', () => {
        it('post processes return values', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY_WITH_OPEN_CHOICE)
            }).toDispatchActions(['loadSurveySuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSurveyMultipleChoiceResults({ questionIndex: 0 })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    surveyMultipleChoiceResults: {
                        0: {
                            labels: ['Tutorials', 'Customer case studies', 'Other choice', 'Product announcements'],
                            data: [336, 312, 20, 0],
                        },
                    },
                })
        })
    })
})

describe('single choice survey with open choice logic', () => {
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
                            ['"Yes"', 101],
                            ['"Only if I could customize my choices"', 1],
                        ],
                    },
                ],
            },
        })
    })

    describe('main', () => {
        it('post processes return values', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SINGLE_CHOICE_SURVEY_WITH_OPEN_CHOICE)
            }).toDispatchActions(['loadSurveySuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSurveySingleChoiceResults({ questionIndex: 1 })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    surveySingleChoiceResults: {
                        1: {
                            labels: ['"Yes"', '"Only if I could customize my choices"'],
                            data: [101, 1],
                            total: 102,
                        },
                    },
                })
        })
    })
})
