import { expectLogic, partial } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import {
    mergeResponsesByQuestion,
    processOpenEndedResults,
    processResultsForSurveyQuestions,
    surveyLogic,
} from 'scenes/surveys/surveyLogic'
import { OpenEndedColumnMap } from 'scenes/surveys/utils'

import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AnyPropertyFilter,
    ChoiceQuestionProcessedResponses,
    EventPropertyFilter,
    OpenQuestionProcessedResponses,
    PropertyFilterType,
    PropertyOperator,
    ResponsesByQuestion,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyEventStats,
    SurveyPosition,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveyRates,
    SurveySchedule,
    SurveyStats,
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
    user_access_level: AccessControlLevel.Editor,
}

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
        user_access_level: AccessControlLevel.Editor,
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

    it('handles group property filters correctly', async () => {
        const groupPropertyFilters: AnyPropertyFilter[] = [
            {
                key: 'name',
                value: 'ACME Corp',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Group,
                group_type_index: 0,
            },
            {
                key: 'industry',
                value: 'technology',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Group,
                group_type_index: 0,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(groupPropertyFilters)
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: groupPropertyFilters,
                dataTableQuery: partial({
                    source: partial({
                        properties: expect.arrayContaining([
                            {
                                key: 'name',
                                value: 'ACME Corp',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Group,
                                group_type_index: 0,
                            },
                            {
                                key: 'industry',
                                value: 'technology',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Group,
                                group_type_index: 0,
                            },
                        ]),
                    }),
                }),
            })
    })

    it('handles mixed property and group filters correctly', async () => {
        const mixedFilters: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: 'test@posthog.com',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
            {
                key: 'company_name',
                value: 'ACME Corp',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Group,
                group_type_index: 0,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(mixedFilters)
        })
            .toDispatchActions(['loadSurveySuccess', 'setPropertyFilters'])
            .toMatchValues({
                propertyFilters: mixedFilters,
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
                                key: 'company_name',
                                value: 'ACME Corp',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Group,
                                group_type_index: 0,
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
                                key: SurveyEventProperties.SURVEY_ID,
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
                                key: SurveyEventProperties.SURVEY_ID,
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

describe('URL parameter synchronization', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = surveyLogic({ id: MULTIPLE_CHOICE_SURVEY.id })
        logic.mount()
    })

    it('only includes non-empty filters in URL', async () => {
        const propertyFilters: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: 'test@posthog.com',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        const emptyAnswerFilters: EventPropertyFilter[] = [
            {
                key: SurveyEventProperties.SURVEY_RESPONSE,
                value: [],
                operator: PropertyOperator.IContains,
                type: PropertyFilterType.Event,
            },
        ]

        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
            logic.actions.setPropertyFilters(propertyFilters)
            logic.actions.setAnswerFilters(emptyAnswerFilters)
        }).toMatchValues({
            urlSearchParams: expect.objectContaining({
                propertyFilters: JSON.stringify(propertyFilters),
            }),
        })

        expect(logic.values.urlSearchParams).not.toHaveProperty('answerFilters')
    })

    it('excludes default date range from URL', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSurveySuccess(MULTIPLE_CHOICE_SURVEY)
        })

        const defaultDateFrom = logic.values.dateRange?.date_from
        const defaultDateTo = logic.values.dateRange?.date_to

        await expectLogic(logic, () => {
            logic.actions.setDateRange(
                {
                    date_from: defaultDateFrom || null,
                    date_to: defaultDateTo || null,
                },
                false
            )
        }).toMatchValues({
            urlSearchParams: expect.not.objectContaining({
                date_from: expect.anything(),
                date_to: expect.anything(),
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
            key: SurveyEventProperties.SURVEY_RESPONSE,
            value: 'test response',
            operator: PropertyOperator.IContains,
            type: PropertyFilterType.Event,
        }

        await expectLogic(logic, () => {
            logic.actions.setAnswerFilters([answerFilter])
        }).toDispatchActions(['setAnswerFilters', 'loadSurveyBaseStats', 'loadSurveyDismissedAndSentCount'])
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

describe('survey stats calculation', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    const MOCK_SURVEY_ID = 'test_survey_id'
    const MOCK_DATE_FORMAT = 'YYYY-MM-DDTHH:mm:ss[Z]'
    const MOCK_FIRST_SEEN = dayjs('2024-01-01T10:00:00Z').format(MOCK_DATE_FORMAT)
    const MOCK_LAST_SEEN = dayjs('2024-01-10T12:00:00Z').format(MOCK_DATE_FORMAT)

    // Helper to create base stats tuple
    const createBaseStat = (
        eventName: SurveyEventName,
        totalCount: number,
        uniquePersons: number,
        firstSeen: string | null = MOCK_FIRST_SEEN,
        lastSeen: string | null = MOCK_LAST_SEEN
    ): [string, number, number, string | null, string | null] => [
        eventName,
        totalCount,
        uniquePersons,
        firstSeen,
        lastSeen,
    ]

    // Helper to create expected EventStats
    const createExpectedEventStat = (
        totalCount: number,
        uniquePersons: number,
        uniquePersonsOnlySeen = 0,
        totalCountOnlySeen = 0,
        firstSeen: string | null = MOCK_FIRST_SEEN,
        lastSeen: string | null = MOCK_LAST_SEEN
    ): SurveyEventStats => ({
        total_count: totalCount,
        unique_persons: uniquePersons,
        first_seen: firstSeen ? dayjs(firstSeen).toISOString() : null,
        last_seen: lastSeen ? dayjs(lastSeen).toISOString() : null,
        unique_persons_only_seen: uniquePersonsOnlySeen,
        total_count_only_seen: totalCountOnlySeen,
    })

    beforeEach(() => {
        initKeaTests()
        logic = surveyLogic({ id: MOCK_SURVEY_ID })
        logic.mount()
    })

    it('should return null stats and zero rates when no base stats results', async () => {
        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(null)
            logic.actions.setDismissedAndSentCount(null)
        }).toMatchValues({
            processedSurveyStats: null,
            surveyRates: {
                response_rate: 0.0,
                dismissal_rate: 0.0,
                unique_users_response_rate: 0.0,
                unique_users_dismissal_rate: 0.0,
            },
        })
    })

    it('should calculate stats correctly when only "survey shown" events exist', async () => {
        const baseStats = [createBaseStat(SurveyEventName.SHOWN, 100, 80)]
        const expectedStats: SurveyStats = {
            [SurveyEventName.SHOWN]: createExpectedEventStat(100, 80, 80, 100), // All shown are only_seen
            [SurveyEventName.DISMISSED]: createExpectedEventStat(0, 0, 0, 0, null, null),
            [SurveyEventName.SENT]: createExpectedEventStat(0, 0, 0, 0, null, null),
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(0)
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: {
                response_rate: 0.0,
                dismissal_rate: 0.0,
                unique_users_response_rate: 0.0,
                unique_users_dismissal_rate: 0.0,
            },
        })
    })

    it('should calculate stats and rates correctly for shown and sent events (no overlap)', async () => {
        const baseStats = [createBaseStat(SurveyEventName.SHOWN, 100, 80), createBaseStat(SurveyEventName.SENT, 50, 40)]
        const expectedStats: SurveyStats = {
            [SurveyEventName.SHOWN]: createExpectedEventStat(100, 80, 40, 50), // 80 unique shown - 40 unique sent = 40 only seen
            [SurveyEventName.DISMISSED]: createExpectedEventStat(0, 0, 0, 0, null, null),
            [SurveyEventName.SENT]: createExpectedEventStat(50, 40),
        }
        const expectedRates: SurveyRates = {
            response_rate: 50.0, // 50 / 100
            dismissal_rate: 0.0,
            unique_users_response_rate: 50.0, // 40 / 80
            unique_users_dismissal_rate: 0.0,
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(0) // No overlap
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: expectedRates,
        })
    })

    it('should calculate stats and rates correctly for shown and dismissed events (no overlap)', async () => {
        const baseStats = [
            createBaseStat(SurveyEventName.SHOWN, 100, 80),
            createBaseStat(SurveyEventName.DISMISSED, 20, 15),
        ]
        const expectedStats: SurveyStats = {
            [SurveyEventName.SHOWN]: createExpectedEventStat(100, 80, 65, 80), // 80 unique shown - 15 unique dismissed = 65 only seen
            [SurveyEventName.DISMISSED]: createExpectedEventStat(20, 15), // Dismissed count remains 15 as overlap is 0
            [SurveyEventName.SENT]: createExpectedEventStat(0, 0, 0, 0, null, null),
        }
        const expectedRates: SurveyRates = {
            response_rate: 0.0,
            dismissal_rate: 20.0, // 20 / 100
            unique_users_response_rate: 0.0,
            unique_users_dismissal_rate: 18.75, // 15 / 80
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(0) // No overlap
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: expectedRates,
        })
    })

    it('should calculate stats and rates correctly for shown, sent, and dismissed events (no overlap)', async () => {
        const baseStats = [
            createBaseStat(SurveyEventName.SHOWN, 100, 80),
            createBaseStat(SurveyEventName.SENT, 50, 40),
            createBaseStat(SurveyEventName.DISMISSED, 20, 15),
        ]
        const expectedStats: SurveyStats = {
            // 80 unique shown - 40 unique sent - 15 unique dismissed = 25 only seen
            // 100 total shown - 50 total sent - 20 total dismissed = 30 only seen
            [SurveyEventName.SHOWN]: createExpectedEventStat(100, 80, 25, 30),
            [SurveyEventName.DISMISSED]: createExpectedEventStat(20, 15), // Dismissed unique count remains 15
            [SurveyEventName.SENT]: createExpectedEventStat(50, 40),
        }
        const expectedRates: SurveyRates = {
            response_rate: 50.0, // 50 / 100
            dismissal_rate: 20.0, // 20 / 100
            unique_users_response_rate: 50.0, // 40 / 80
            unique_users_dismissal_rate: 18.75, // 15 / 80
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(0) // No overlap
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: expectedRates,
        })
    })

    it('should correctly adjust dismissed unique count and calculate rates with overlap', async () => {
        const baseStats = [
            createBaseStat(SurveyEventName.SHOWN, 100, 80),
            createBaseStat(SurveyEventName.SENT, 50, 40),
            createBaseStat(SurveyEventName.DISMISSED, 20, 15), // Initially 15 unique dismissed
        ]
        const dismissedAndSentOverlap = 5 // 5 people both dismissed AND sent

        // Expected adjusted dismissed unique count = 15 (initial) - 5 (overlap) = 10
        const expectedStats: SurveyStats = {
            // 80 unique shown - 40 unique sent - 10 unique dismissed (adjusted) = 30 only seen
            // 100 total shown - 50 total sent - 20 total dismissed = 30 only seen
            [SurveyEventName.SHOWN]: createExpectedEventStat(100, 80, 30, 30),
            [SurveyEventName.DISMISSED]: createExpectedEventStat(20, 10), // Adjusted unique count is 10
            [SurveyEventName.SENT]: createExpectedEventStat(50, 40),
        }
        const expectedRates: SurveyRates = {
            response_rate: 50.0, // 50 / 100
            dismissal_rate: 20.0, // 20 / 100
            unique_users_response_rate: 50.0, // 40 / 80
            unique_users_dismissal_rate: 12.5, // 10 (adjusted unique dismissed) / 80
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(dismissedAndSentOverlap)
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: expectedRates,
        })
    })

    it('should handle zero counts correctly', async () => {
        const baseStats = [
            createBaseStat(SurveyEventName.SHOWN, 0, 0, null, null),
            createBaseStat(SurveyEventName.SENT, 0, 0, null, null),
            createBaseStat(SurveyEventName.DISMISSED, 0, 0, null, null),
        ]
        const expectedStats: SurveyStats = {
            [SurveyEventName.SHOWN]: createExpectedEventStat(0, 0, 0, 0, null, null),
            [SurveyEventName.DISMISSED]: createExpectedEventStat(0, 0, 0, 0, null, null),
            [SurveyEventName.SENT]: createExpectedEventStat(0, 0, 0, 0, null, null),
        }
        const expectedRates: SurveyRates = {
            response_rate: 0.0,
            dismissal_rate: 0.0,
            unique_users_response_rate: 0.0,
            unique_users_dismissal_rate: 0.0,
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(0)
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: expectedRates,
        })
    })

    it('should handle case where dismissed unique count equals overlap', async () => {
        const baseStats = [
            createBaseStat(SurveyEventName.SHOWN, 100, 80),
            createBaseStat(SurveyEventName.SENT, 50, 40),
            createBaseStat(SurveyEventName.DISMISSED, 20, 15), // Initially 15 unique dismissed
        ]
        const dismissedAndSentOverlap = 15 // Overlap equals initial unique dismissed

        // Expected adjusted dismissed unique count = 15 (initial) - 15 (overlap) = 0
        const expectedStats: SurveyStats = {
            // 80 unique shown - 40 unique sent - 0 unique dismissed (adjusted) = 40 only seen
            // 100 total shown - 50 total sent - 20 total dismissed = 30 only seen
            [SurveyEventName.SHOWN]: createExpectedEventStat(100, 80, 40, 30),
            [SurveyEventName.DISMISSED]: createExpectedEventStat(20, 0), // Adjusted unique count is 0
            [SurveyEventName.SENT]: createExpectedEventStat(50, 40),
        }
        const expectedRates: SurveyRates = {
            response_rate: 50.0,
            dismissal_rate: 20.0,
            unique_users_response_rate: 50.0,
            unique_users_dismissal_rate: 0.0, // 0 (adjusted unique dismissed) / 80
        }

        await expectLogic(logic, () => {
            logic.actions.setBaseStatsResults(baseStats)
            logic.actions.setDismissedAndSentCount(dismissedAndSentOverlap)
        }).toMatchValues({
            processedSurveyStats: expectedStats,
            surveyRates: expectedRates,
        })
    })
})

describe('processResultsForSurveyQuestions', () => {
    // Input format: AggregateRow[] = [question_id, label, count][]
    describe('Rating Questions', () => {
        it.each([
            {
                name: '10-point NPS scale (0-10)',
                scale: 10 as const,
                rows: [
                    ['rating-q', '0', 1],
                    ['rating-q', '5', 2],
                    ['rating-q', '10', 1],
                ] as [string, string, number][],
                expectedTotal: 4,
                expectedLength: 11,
                expectedSlots: [
                    { index: 0, label: '0', value: 1 },
                    { index: 5, label: '5', value: 2 },
                    { index: 10, label: '10', value: 1 },
                    { index: 1, label: '1', value: 0 },
                ],
            },
            {
                name: '5-point scale (1-5)',
                scale: 5 as const,
                rows: [
                    ['rating-q', '1', 1],
                    ['rating-q', '3', 2],
                    ['rating-q', '5', 1],
                ] as [string, string, number][],
                expectedTotal: 4,
                expectedLength: 5,
                expectedSlots: [
                    { index: 0, label: '1', value: 1 },
                    { index: 1, label: '2', value: 0 },
                    { index: 2, label: '3', value: 2 },
                    { index: 3, label: '4', value: 0 },
                    { index: 4, label: '5', value: 1 },
                ],
            },
            {
                name: '3-point scale rejects out-of-range values',
                scale: 3 as const,
                rows: [
                    ['rating-q', '1', 1],
                    ['rating-q', '2', 1],
                    ['rating-q', '3', 1],
                    ['rating-q', '0', 1],
                ] as [string, string, number][],
                expectedTotal: 3,
                expectedLength: 3,
                expectedSlots: [
                    { index: 0, label: '1', value: 1 },
                    { index: 1, label: '2', value: 1 },
                    { index: 2, label: '3', value: 1 },
                ],
            },
        ])('processes $name', ({ scale, rows, expectedTotal, expectedLength, expectedSlots }) => {
            const questions = [
                {
                    id: 'rating-q',
                    type: SurveyQuestionType.Rating as const,
                    question: 'Rate us',
                    scale,
                    display: 'number' as const,
                    lowerBoundLabel: 'Poor',
                    upperBoundLabel: 'Excellent',
                },
            ]

            const processed = processResultsForSurveyQuestions(questions, rows)
            const ratingData = processed['rating-q'] as ChoiceQuestionProcessedResponses

            expect(ratingData.type).toBe(SurveyQuestionType.Rating)
            expect(ratingData.totalResponses).toBe(expectedTotal)
            expect(ratingData.data).toHaveLength(expectedLength)

            for (const { index, label, value } of expectedSlots) {
                expect(ratingData.data[index]).toEqual({ label, value, isPredefined: true })
            }
        })

        it('ignores non-numeric labels', () => {
            const questions = [
                {
                    id: 'rating-q',
                    type: SurveyQuestionType.Rating as const,
                    question: 'Rate us',
                    scale: 5 as const,
                    display: 'number' as const,
                    lowerBoundLabel: 'Poor',
                    upperBoundLabel: 'Excellent',
                },
            ]
            const rows: [string, string, number][] = [
                ['rating-q', 'invalid', 3],
                ['rating-q', '3', 2],
            ]

            const processed = processResultsForSurveyQuestions(questions, rows)
            const ratingData = processed['rating-q'] as ChoiceQuestionProcessedResponses

            expect(ratingData.totalResponses).toBe(2)
        })
    })

    describe('Single Choice Questions', () => {
        it('processes counts, sorts by value, and zero-fills predefined choices', () => {
            const questions = [
                {
                    id: 'single-q1',
                    type: SurveyQuestionType.SingleChoice as const,
                    question: 'Pick one',
                    choices: ['Yes', 'No', 'Maybe'],
                },
            ]
            const rows: [string, string, number][] = [
                ['single-q1', 'Yes', 2],
                ['single-q1', 'No', 1],
                ['single-q1', 'Custom answer', 1],
            ]

            const processed = processResultsForSurveyQuestions(questions, rows)
            const singleData = processed['single-q1'] as ChoiceQuestionProcessedResponses

            expect(singleData.type).toBe(SurveyQuestionType.SingleChoice)
            expect(singleData.totalResponses).toBe(4)

            const dataMap = new Map(singleData.data.map((item) => [item.label, item]))
            expect(dataMap.get('Yes')).toEqual({ label: 'Yes', value: 2, isPredefined: true })
            expect(dataMap.get('No')).toEqual({ label: 'No', value: 1, isPredefined: true })
            expect(dataMap.get('Maybe')).toEqual({ label: 'Maybe', value: 0, isPredefined: true })
            expect(dataMap.get('Custom answer')).toEqual({ label: 'Custom answer', value: 1, isPredefined: false })
        })
    })

    describe('Multiple Choice Questions', () => {
        it('uses __total__ for totalResponses and counts per-choice', () => {
            const questions = [
                {
                    id: 'multi-q1',
                    type: SurveyQuestionType.MultipleChoice as const,
                    question: 'Pick many',
                    choices: ['A', 'B', 'C'],
                },
            ]
            const rows: [string, string, number][] = [
                ['multi-q1', 'A', 2],
                ['multi-q1', 'B', 1],
                ['multi-q1', 'C', 1],
                ['multi-q1', 'Custom', 1],
                ['multi-q1', '__total__', 3],
            ]

            const processed = processResultsForSurveyQuestions(questions, rows)
            const multiData = processed['multi-q1'] as ChoiceQuestionProcessedResponses

            expect(multiData.type).toBe(SurveyQuestionType.MultipleChoice)
            expect(multiData.totalResponses).toBe(3)

            const dataMap = new Map(multiData.data.map((item) => [item.label, item]))
            expect(dataMap.get('A')).toEqual({ label: 'A', value: 2, isPredefined: true })
            expect(dataMap.get('B')).toEqual({ label: 'B', value: 1, isPredefined: true })
            expect(dataMap.get('C')).toEqual({ label: 'C', value: 1, isPredefined: true })
            expect(dataMap.get('Custom')).toEqual({ label: 'Custom', value: 1, isPredefined: false })
        })
    })

    describe('Open Questions', () => {
        it('returns total count with empty data (raw data comes from open-ended query)', () => {
            const questions = [
                {
                    id: 'open-q1',
                    type: SurveyQuestionType.Open as const,
                    question: 'Tell us more',
                },
            ]
            const rows: [string, string, number][] = [['open-q1', '__total__', 42]]

            const processed = processResultsForSurveyQuestions(questions, rows)
            const openData = processed['open-q1'] as OpenQuestionProcessedResponses

            expect(openData.type).toBe(SurveyQuestionType.Open)
            expect(openData.totalResponses).toBe(42)
            expect(openData.data).toHaveLength(0)
        })
    })

    it('returns empty object for null rows', () => {
        const questions = [{ id: 'q1', type: SurveyQuestionType.Open as const, question: 'Q' }]
        expect(processResultsForSurveyQuestions(questions, null)).toEqual({})
    })

    it('skips Link questions', () => {
        const questions = [
            { id: 'link-q', type: SurveyQuestionType.Link as const, question: 'Visit', link: 'https://example.com' },
        ]
        const rows: [string, string, number][] = [['link-q', '__total__', 5]]
        expect(processResultsForSurveyQuestions(questions, rows)).toEqual({})
    })

    it('handles multiple questions in one result set', () => {
        const questions = [
            {
                id: 'rating-q',
                type: SurveyQuestionType.Rating as const,
                question: 'Rate',
                scale: 5 as const,
                display: 'number' as const,
                lowerBoundLabel: '',
                upperBoundLabel: '',
            },
            {
                id: 'choice-q',
                type: SurveyQuestionType.SingleChoice as const,
                question: 'Pick',
                choices: ['A', 'B'],
            },
        ]
        const rows: [string, string, number][] = [
            ['rating-q', '3', 10],
            ['choice-q', 'A', 5],
            ['choice-q', 'B', 3],
        ]

        const processed = processResultsForSurveyQuestions(questions, rows)
        expect(processed['rating-q']).not.toBeUndefined()
        expect(processed['choice-q']).not.toBeUndefined()
        expect((processed['choice-q'] as ChoiceQuestionProcessedResponses).totalResponses).toBe(8)
    })
})

describe('processOpenEndedResults', () => {
    it('collects raw responses for open text questions', () => {
        const questions = [{ id: 'open-q1', type: SurveyQuestionType.Open as const, question: 'Tell us more' }]
        const columnMap: OpenEndedColumnMap = {
            'open-q1': { columnIndex: 0, questionIndex: 0, type: SurveyQuestionType.Open },
        }
        const rows = [
            ['Great product!', 'user123', '2024-01-15T10:30:00Z'],
            ['Could be better', 'user456', '2024-01-15T11:45:00Z'],
            ['', 'user789', '2024-01-15T12:00:00Z'],
        ]

        const result = processOpenEndedResults(questions, columnMap, rows)
        const openData = result['open-q1'] as OpenQuestionProcessedResponses

        expect(openData.type).toBe(SurveyQuestionType.Open)
        expect(openData.totalResponses).toBe(2)
        expect(openData.data).toHaveLength(2)
        expect(openData.data[0]).toEqual({
            distinctId: 'user123',
            response: 'Great product!',
            timestamp: '2024-01-15T10:30:00Z',
        })
        expect(openData.data[1]).toEqual({
            distinctId: 'user456',
            response: 'Could be better',
            timestamp: '2024-01-15T11:45:00Z',
        })
    })

    it('collects non-predefined "Other" text from single choice with hasOpenChoice', () => {
        const questions = [
            {
                id: 'choice-q1',
                type: SurveyQuestionType.SingleChoice as const,
                question: 'Pick one',
                choices: ['Yes', 'No', 'Other'],
                hasOpenChoice: true,
            },
        ]
        const columnMap: OpenEndedColumnMap = {
            'choice-q1': { columnIndex: 0, questionIndex: 0, type: SurveyQuestionType.SingleChoice },
        }
        const rows = [
            ['Yes', 'user1', '2024-01-15T10:00:00Z'],
            ['Something custom', 'user2', '2024-01-15T11:00:00Z'],
            ['No', 'user3', '2024-01-15T12:00:00Z'],
        ]

        const result = processOpenEndedResults(questions, columnMap, rows)
        const choiceData = result['choice-q1'] as ChoiceQuestionProcessedResponses

        expect(choiceData.data).toHaveLength(1)
        expect(choiceData.data[0].label).toBe('Something custom')
        expect(choiceData.data[0].distinctId).toBe('user2')
    })

    it('collects non-predefined "Other" text from multiple choice with hasOpenChoice', () => {
        const questions = [
            {
                id: 'multi-q1',
                type: SurveyQuestionType.MultipleChoice as const,
                question: 'Pick many',
                choices: ['A', 'B', 'Other'],
                hasOpenChoice: true,
            },
        ]
        const columnMap: OpenEndedColumnMap = {
            'multi-q1': { columnIndex: 0, questionIndex: 0, type: SurveyQuestionType.MultipleChoice },
        }
        const rows = [
            [['A', 'Custom text'], 'user1', '2024-01-15T10:00:00Z'],
            [['B'], 'user2', '2024-01-15T11:00:00Z'],
        ]

        const result = processOpenEndedResults(questions, columnMap, rows)
        const choiceData = result['multi-q1'] as ChoiceQuestionProcessedResponses

        expect(choiceData.data).toHaveLength(1)
        expect(choiceData.data[0].label).toBe('Custom text')
    })

    it('returns empty object for null rows', () => {
        expect(processOpenEndedResults([], {}, null)).toEqual({})
    })
})

describe('mergeResponsesByQuestion', () => {
    it('merges open question: takes data from open-ended, totalResponses from aggregate', () => {
        const aggregate: ResponsesByQuestion = {
            'open-q': { type: SurveyQuestionType.Open, data: [], totalResponses: 100 },
        }
        const openEnded: ResponsesByQuestion = {
            'open-q': {
                type: SurveyQuestionType.Open,
                data: [{ distinctId: 'u1', response: 'Great', timestamp: '2024-01-15T10:00:00Z' }],
                totalResponses: 1,
            },
        }

        const merged = mergeResponsesByQuestion(aggregate, openEnded)
        const result = merged['open-q'] as OpenQuestionProcessedResponses

        expect(result.data).toHaveLength(1)
        expect(result.totalResponses).toBe(100)
    })

    it('merges choice question with open choice: appends "Other" data to aggregate data', () => {
        const aggregate: ResponsesByQuestion = {
            'choice-q': {
                type: SurveyQuestionType.SingleChoice,
                data: [{ label: 'Yes', value: 5, isPredefined: true }],
                totalResponses: 6,
                noResponseCount: 0,
            },
        }
        const openEnded: ResponsesByQuestion = {
            'choice-q': {
                type: SurveyQuestionType.SingleChoice,
                data: [{ label: 'Custom answer', value: 1, isPredefined: false, distinctId: 'u1', timestamp: 'ts' }],
                totalResponses: 0,
                noResponseCount: 0,
            },
        }

        const merged = mergeResponsesByQuestion(aggregate, openEnded)
        const result = merged['choice-q'] as ChoiceQuestionProcessedResponses

        expect(result.data).toHaveLength(2)
        expect(result.totalResponses).toBe(6)
    })

    it('passes through aggregate-only questions unchanged', () => {
        const aggregate: ResponsesByQuestion = {
            'rating-q': {
                type: SurveyQuestionType.Rating,
                data: [{ label: '5', value: 10, isPredefined: true }],
                totalResponses: 10,
                noResponseCount: 0,
            },
        }

        const merged = mergeResponsesByQuestion(aggregate, {})
        expect(merged['rating-q']).toEqual(aggregate['rating-q'])
    })

    it('passes through open-ended-only questions when no aggregate exists', () => {
        const openEnded: ResponsesByQuestion = {
            'open-q': {
                type: SurveyQuestionType.Open,
                data: [{ distinctId: 'u1', response: 'Hello', timestamp: 'ts' }],
                totalResponses: 1,
            },
        }

        const merged = mergeResponsesByQuestion({}, openEnded)
        expect(merged['open-q']).toEqual(openEnded['open-q'])
    })
})
