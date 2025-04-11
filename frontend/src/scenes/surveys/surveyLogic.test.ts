import { expectLogic, partial } from 'kea-test-utils'
import { dayjs } from 'lib/dayjs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AnyPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyPosition,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

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
        position: SurveyPosition.Right,
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
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
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
        position: SurveyPosition.Right,
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
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
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
        position: SurveyPosition.Right,
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
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
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
        position: SurveyPosition.Right,
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
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
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
                '/api/environments/:team_id/query/': () => [
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
                '/api/environments/:team_id/query/': () => [
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
                '/api/environments/:team_id/query/': () => [
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
                '/api/environments/:team_id/query/': () => [
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

describe('set response-based survey branching', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = surveyLogic({ id: 'new' })
        logic.mount()
    })

    const SURVEY: Survey = {
        id: '118b22a3-09b1-0000-2f5b-1bd8352ceec9',
        name: 'My survey',
        description: '',
        type: SurveyType.Popover,
        linked_flag: null,
        linked_flag_id: null,
        targeting_flag: null,
        questions: [],
        conditions: null,
        appearance: {
            position: SurveyPosition.Right,
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
        responses_limit: null,
        schedule: SurveySchedule.Once,
    }

    describe('main', () => {
        // Single-choice question
        it('set response-based branching for a single-choice question', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: 'Are you happy with our service?',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Glad to hear that. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Sorry to hear that. Tell us more!',
                    description: '',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            const questionIndex = 0

            await expectLogic(logic, () => {
                logic.actions.setQuestionBranchingType(
                    questionIndex,
                    SurveyQuestionBranchingType.ResponseBased,
                    undefined
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'Yes',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    1
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'No',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    2
                )
            })
                .toDispatchActions([
                    'setQuestionBranchingType',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                ])
                .toMatchValues({
                    survey: partial({
                        questions: [
                            {
                                ...SURVEY.questions[0],
                                branching: {
                                    type: SurveyQuestionBranchingType.ResponseBased,
                                    responseValues: { Yes: 1, No: 2 },
                                },
                            },
                            { ...SURVEY.questions[1] },
                            { ...SURVEY.questions[2] },
                        ],
                    }),
                })
        })

        // Rating question, scale 1-3
        it('set response-based branching for a rating question with scale 3', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: 'How happy are you?',
                    description: '',
                    display: 'number',
                    scale: 3,
                    lowerBoundLabel: 'Unhappy',
                    upperBoundLabel: 'Happy',
                    buttonText: 'Submit',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Sorry to hear that. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Seems you are not completely happy. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Glad to hear that. Tell us more!',
                    description: '',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            const questionIndex = 0

            await expectLogic(logic, () => {
                logic.actions.setQuestionBranchingType(
                    questionIndex,
                    SurveyQuestionBranchingType.ResponseBased,
                    undefined
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'negative',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    1
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'neutral',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    2
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'positive',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    3
                )
            })
                .toDispatchActions([
                    'setQuestionBranchingType',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                ])
                .toMatchValues({
                    survey: partial({
                        questions: [
                            {
                                ...SURVEY.questions[0],
                                branching: {
                                    type: SurveyQuestionBranchingType.ResponseBased,
                                    responseValues: { negative: 1, neutral: 2, positive: 3 },
                                },
                            },
                            { ...SURVEY.questions[1] },
                            { ...SURVEY.questions[2] },
                            { ...SURVEY.questions[3] },
                        ],
                    }),
                })
        })

        // Rating question, scale 1-5
        it('set response-based branching for a rating question with scale 5', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: 'How happy are you?',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unhappy',
                    upperBoundLabel: 'Happy',
                    buttonText: 'Submit',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Sorry to hear that. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Seems you are not completely happy. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Glad to hear that. Tell us more!',
                    description: '',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            const questionIndex = 0

            await expectLogic(logic, () => {
                logic.actions.setQuestionBranchingType(
                    questionIndex,
                    SurveyQuestionBranchingType.ResponseBased,
                    undefined
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'negative',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    1
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'neutral',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    2
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'positive',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    3
                )
            })
                .toDispatchActions([
                    'setQuestionBranchingType',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                ])
                .toMatchValues({
                    survey: partial({
                        questions: [
                            {
                                ...SURVEY.questions[0],
                                branching: {
                                    type: SurveyQuestionBranchingType.ResponseBased,
                                    responseValues: { negative: 1, neutral: 2, positive: 3 },
                                },
                            },
                            { ...SURVEY.questions[1] },
                            { ...SURVEY.questions[2] },
                            { ...SURVEY.questions[3] },
                        ],
                    }),
                })
        })

        // Rating question, scale 0-10 (NPS)
        it('set response-based branching for a rating question with scale 10', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: 'How happy are you?',
                    description: '',
                    display: 'number',
                    scale: 10,
                    lowerBoundLabel: 'Unhappy',
                    upperBoundLabel: 'Happy',
                    buttonText: 'Submit',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Sorry to hear that. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Seems you are not completely happy. Tell us more!',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Glad to hear that. Tell us more!',
                    description: '',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            const questionIndex = 0

            await expectLogic(logic, () => {
                logic.actions.setQuestionBranchingType(
                    questionIndex,
                    SurveyQuestionBranchingType.ResponseBased,
                    undefined
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'detractors',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    1
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'passives',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    2
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    'promoters',
                    SurveyQuestionBranchingType.SpecificQuestion,
                    3
                )
            })
                .toDispatchActions([
                    'setQuestionBranchingType',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                ])
                .toMatchValues({
                    survey: partial({
                        questions: [
                            {
                                ...SURVEY.questions[0],
                                branching: {
                                    type: SurveyQuestionBranchingType.ResponseBased,
                                    responseValues: { detractors: 1, passives: 2, promoters: 3 },
                                },
                            },
                            { ...SURVEY.questions[1] },
                            { ...SURVEY.questions[2] },
                            { ...SURVEY.questions[3] },
                        ],
                    }),
                })
        })

        // Branch out to Next question / Confirmation message
        it('branch out to next question or confirmation message', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: 'Are you happy with our service?',
                    description: '',
                },
                {
                    type: SurveyQuestionType.Open,
                    question: 'Sorry to hear that. Tell us more!',
                    description: '',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            }).toDispatchActions(['loadSurveySuccess'])

            const questionIndex = 0

            await expectLogic(logic, () => {
                logic.actions.setQuestionBranchingType(
                    questionIndex,
                    SurveyQuestionBranchingType.ResponseBased,
                    undefined
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    0,
                    SurveyQuestionBranchingType.End,
                    undefined
                )
                logic.actions.setResponseBasedBranchingForQuestion(
                    questionIndex,
                    1,
                    SurveyQuestionBranchingType.NextQuestion,
                    undefined
                )
            })
                .toDispatchActions([
                    'setQuestionBranchingType',
                    'setResponseBasedBranchingForQuestion',
                    'setResponseBasedBranchingForQuestion',
                ])
                .toMatchValues({
                    survey: partial({
                        questions: [
                            {
                                ...SURVEY.questions[0],
                                branching: {
                                    type: SurveyQuestionBranchingType.ResponseBased,
                                    responseValues: { 0: SurveyQuestionBranchingType.End }, // Branching out to "Next question" is implicit
                                },
                            },
                            { ...SURVEY.questions[1] },
                        ],
                    }),
                })
        })

        it('should detect a cycle', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 1,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 0,
                    },
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: true,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 1,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 2,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '2',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 1,
                    },
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: true,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 2: 1 },
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 3: 0 },
                    },
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: true,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 2: 3 },
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '2',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '3',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 3: 5 },
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '4',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 2,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '5',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: true,
                })
        })

        it('should not detect a cycle', async () => {
            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '2',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 1,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 1,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 2,
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '2',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 2: 1, 5: SurveyQuestionBranchingType.End },
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 3: SurveyQuestionBranchingType.End },
                    },
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.Rating,
                    question: '0',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 2: 3 },
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '1',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '2',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '3',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 3: 5 },
                    },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '4',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                    branching: { type: SurveyQuestionBranchingType.End },
                },
                {
                    type: SurveyQuestionType.Rating,
                    question: '5',
                    description: '',
                    display: 'number',
                    scale: 5,
                    lowerBoundLabel: 'Unlikely',
                    upperBoundLabel: 'Very likely',
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })

            SURVEY.questions = [
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: '0',
                    description: '',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 0: 1, 1: 2 },
                    },
                },
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: '1',
                    description: '',
                    branching: {
                        type: SurveyQuestionBranchingType.ResponseBased,
                        responseValues: { 0: 2, 1: 3 },
                    },
                },
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: '2',
                    description: '',
                    branching: {
                        type: SurveyQuestionBranchingType.SpecificQuestion,
                        index: 4,
                    },
                },
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: '3',
                    description: '',
                    branching: {
                        type: SurveyQuestionBranchingType.End,
                    },
                },
                {
                    type: SurveyQuestionType.SingleChoice,
                    choices: ['Yes', 'No'],
                    question: '4',
                    description: '',
                },
            ]
            await expectLogic(logic, () => {
                logic.actions.loadSurveySuccess(SURVEY)
            })
                .toDispatchActions(['loadSurveySuccess'])
                .toMatchValues({
                    hasCycle: false,
                })
        })
    })
})

describe('survey filters', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = surveyLogic({ id: 'new' })
        logic.mount()
    })

    it('applies property filters to queries', async () => {
        const propertyFilters: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: 'test@posthog.com',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(propertyFilters)
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: propertyFilters,
                dataTableQuery: partial({
                    source: partial({
                        properties: expect.arrayContaining([
                            {
                                key: 'email',
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                        ]),
                    }),
                }),
            })
    })

    it('updates query filters when property filters change', async () => {
        // Set initial filters
        const initialFilters: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: 'test@posthog.com',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(initialFilters)
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: initialFilters,
                dataTableQuery: partial({
                    source: partial({
                        properties: expect.arrayContaining([
                            {
                                key: 'email',
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                        ]),
                    }),
                }),
            })

        // Update filters
        const updatedFilters: AnyPropertyFilter[] = [
            {
                key: 'country',
                value: 'US',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.setPropertyFilters(updatedFilters)
        })
            .toDispatchActions(['setPropertyFilters'])
            .toMatchValues({
                propertyFilters: updatedFilters,
                dataTableQuery: partial({
                    source: partial({
                        properties: expect.arrayContaining([
                            {
                                key: 'country',
                                value: 'US',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                        ]),
                    }),
                }),
            })
    })

    it('handles multiple property filters correctly', async () => {
        const multipleFilters: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: 'test@posthog.com',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
            {
                key: 'country',
                value: 'US',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(multipleFilters)
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: multipleFilters,
                dataTableQuery: partial({
                    source: partial({
                        properties: expect.arrayContaining([
                            {
                                key: 'email',
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                            {
                                key: 'country',
                                value: 'US',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                        ]),
                    }),
                }),
            })
    })

    it('preserves existing query properties when setting filters', async () => {
        const propertyFilters: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: 'test@posthog.com',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(propertyFilters)
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: propertyFilters,
                dataTableQuery: partial({
                    source: partial({
                        properties: expect.arrayContaining([
                            // Survey ID property should still be present
                            {
                                key: '$survey_id',
                                operator: 'exact',
                                type: 'event',
                                value: MULTIPLE_CHOICE_SURVEY.id,
                            },
                            // Our new filter should be present
                            {
                                key: 'email',
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                        ]),
                    }),
                }),
            })
    })

    it('handles empty property filters', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters([])
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: [],
                dataTableQuery: partial({
                    source: partial({
                        // Should still have the survey ID property even with no filters
                        properties: expect.arrayContaining([
                            {
                                key: '$survey_id',
                                operator: 'exact',
                                type: 'event',
                                value: MULTIPLE_CHOICE_SURVEY.id,
                            },
                        ]),
                    }),
                }),
            })
    })
})

describe('surveyLogic filters for surveys responses', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = surveyLogic({ id: 'new' })
        logic.mount()
    })
    it('reloads survey results when answer filters change', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
        }).toDispatchActions(['loadSurveySuccess'])

        const answerFilter: EventPropertyFilter = {
            key: '$survey_response',
            value: 'test response',
            operator: PropertyOperator.IContains,
            type: PropertyFilterType.Event,
        }

        await expectLogic(logic, () => {
            logic.actions.setAnswerFilters([answerFilter])
        }).toDispatchActions(['setAnswerFilters', 'loadSurveyUserStats', 'loadSurveyMultipleChoiceResults'])
    })

    describe('interval selection', () => {
        it('starts with null interval', async () => {
            await expectLogic(logic).toMatchValues({
                interval: null,
            })
        })

        it('calculates default interval based on survey dates', async () => {
            // Test for survey <= 2 days old
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(1, 'day').format('YYYY-MM-DD'))
            }).toMatchValues({
                defaultInterval: 'hour',
            })

            // Test for survey <= 4 weeks old
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(3, 'weeks').format('YYYY-MM-DD'))
            }).toMatchValues({
                defaultInterval: 'day',
            })

            // Test for survey <= 12 weeks old
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(10, 'weeks').format('YYYY-MM-DD'))
            }).toMatchValues({
                defaultInterval: 'week',
            })

            // Test for survey > 12 weeks old
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(16, 'weeks').format('YYYY-MM-DD'))
            }).toMatchValues({
                defaultInterval: 'month',
            })
        })

        it('uses start_date over created_at when available', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(16, 'weeks').format('YYYY-MM-DD'))
                logic.actions.setSurveyValue('start_date', dayjs().subtract(2, 'weeks').format('YYYY-MM-DD'))
            }).toMatchValues({
                defaultInterval: 'day',
            })
        })

        it('uses end_date when available', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(20, 'weeks').format('YYYY-MM-DD'))
                logic.actions.setSurveyValue('end_date', dayjs().subtract(3, 'weeks').format('YYYY-MM-DD'))
            }).toMatchValues({
                defaultInterval: 'month',
            })
        })

        it('allows manual interval override', async () => {
            // Set survey dates that would default to 'day'
            await expectLogic(logic, () => {
                logic.actions.setSurveyValue('created_at', dayjs().subtract(3, 'weeks').format('YYYY-MM-DD'))
            })

            // Override with manual selection
            await expectLogic(logic, () => {
                logic.actions.setInterval('month')
            }).toMatchValues({
                interval: 'month',
                defaultInterval: 'day', // Default interval remains unchanged
            })
        })
    })
})
