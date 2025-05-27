import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import {
    MultipleSurveyQuestion,
    Survey,
    SurveyPosition,
    SurveyQuestion,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import { SurveyEditQuestionGroup } from './SurveyEditQuestionRow'

// Mock the Kea hooks to bypass the need for actual logic
jest.mock('kea', () => {
    const originalModule = jest.requireActual('kea')

    // Create mock functions inside the mock definition
    const mockValues = {
        survey: null, // Will be set in tests
        descriptionContentType: jest.fn(() => 'text'),
    }

    const mockActions = {
        setDefaultForQuestionType: jest.fn(),
        setSurveyValue: jest.fn(),
        resetBranchingForQuestion: jest.fn(),
    }

    return {
        ...originalModule,
        useValues: jest.fn(() => mockValues),
        useActions: jest.fn(() => mockActions),
    }
})

// Mock kea-forms
jest.mock('kea-forms', () => ({
    Form: ({ children }: { children: React.ReactNode }) => <div data-testid="mock-form">{children}</div>,
    Group: ({ name, children }: { name: string; children: React.ReactNode }) => (
        <div data-testid={`mock-group-${name}`}>{children}</div>
    ),
}))

// Mock survey data
const mockSurvey: Survey = {
    id: '123',
    name: 'Test Survey',
    description: '',
    type: SurveyType.Popover,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [
        {
            type: SurveyQuestionType.Rating,
            question: 'How would you rate our product?',
            description: '',
            display: 'number',
            scale: 5,
            lowerBoundLabel: 'Poor',
            upperBoundLabel: 'Excellent',
            buttonText: 'Submit Rating',
        },
        {
            type: SurveyQuestionType.SingleChoice,
            choices: ['Yes', 'No', 'Maybe'],
            question: 'Would you recommend our product?',
            description: '',
            buttonText: 'Send Response',
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

describe('SurveyEditQuestionGroup', () => {
    // Get references to the mocked functions that were created in the jest.mock call
    const keaMock = jest.requireMock('kea')
    const useValuesMock = keaMock.useValues
    const useActionsMock = keaMock.useActions
    const setSurveyValueMock = useActionsMock().setSurveyValue

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()

        // Set the survey value in the mock
        useValuesMock.mockImplementation(() => ({
            survey: mockSurvey,
            descriptionContentType: jest.fn(() => 'text'),
        }))
    })

    it('renders button text input for rating question', () => {
        render(
            <Provider>
                <SurveyEditQuestionGroup index={0} question={mockSurvey.questions[0]} />
            </Provider>
        )

        // Verify button text input is displayed
        const buttonTextInput = screen.getByLabelText('Submit button text')
        expect(buttonTextInput).toBeInTheDocument()
        expect(buttonTextInput).toHaveValue('Submit Rating')
    })

    it('renders button text input for single choice question', () => {
        render(
            <Provider>
                <SurveyEditQuestionGroup index={1} question={mockSurvey.questions[1]} />
            </Provider>
        )

        // Verify button text input is displayed
        const buttonTextInput = screen.getByLabelText('Submit button text')
        expect(buttonTextInput).toBeInTheDocument()
        expect(buttonTextInput).toHaveValue('Send Response')
    })

    it('allows editing button text for rating question', () => {
        render(
            <Provider>
                <SurveyEditQuestionGroup index={0} question={mockSurvey.questions[0]} />
            </Provider>
        )

        // Find the button text input and change its value
        const buttonTextInput = screen.getByLabelText('Submit button text')
        fireEvent.change(buttonTextInput, { target: { value: 'New Submit Text' } })

        // Verify setSurveyValue was called with the correct arguments
        expect(setSurveyValueMock).toHaveBeenCalledWith('questions', [
            { ...mockSurvey.questions[0], buttonText: 'New Submit Text' },
            mockSurvey.questions[1],
        ])
    })

    it('shows "Automatically submit on selection" checkbox for rating questions', () => {
        render(
            <Provider>
                <SurveyEditQuestionGroup index={0} question={mockSurvey.questions[0]} />
            </Provider>
        )

        // Verify the checkbox is displayed
        const checkbox = screen.getByLabelText('Automatically submit on selection')
        expect(checkbox).toBeInTheDocument()
        expect(checkbox).not.toBeChecked()
    })

    it('hides button text input when "Automatically submit on selection" is checked for rating questions', () => {
        // Update the mock to include skipSubmitButton = true
        const questionWithSkipButton = {
            ...mockSurvey.questions[0],
            skipSubmitButton: true,
        }

        useValuesMock.mockImplementation(() => ({
            survey: {
                ...mockSurvey,
                questions: [questionWithSkipButton, mockSurvey.questions[1]],
            },
            descriptionContentType: jest.fn(() => 'text'),
        }))

        render(
            <Provider>
                <SurveyEditQuestionGroup index={0} question={questionWithSkipButton} />
            </Provider>
        )

        // Verify the input field is not in the document
        const buttonTextInputs = screen.queryAllByLabelText('Submit button text')
        expect(buttonTextInputs.length).toBe(1) // Label is still there

        // Verify the actual input field isn't rendered
        const inputField = screen.queryByDisplayValue('Submit Rating')
        expect(inputField).not.toBeInTheDocument()
    })

    it('does not show "Automatically submit on selection" checkbox for open text questions', () => {
        const openTextQuestion: SurveyQuestion = {
            type: SurveyQuestionType.Open,
            question: 'What do you think about our product?',
            description: '',
            buttonText: 'Submit Answer',
        }

        useValuesMock.mockImplementation(() => ({
            survey: {
                ...mockSurvey,
                questions: [openTextQuestion, mockSurvey.questions[1]],
            },
            descriptionContentType: jest.fn(() => 'text'),
        }))

        render(
            <Provider>
                <SurveyEditQuestionGroup index={0} question={openTextQuestion} />
            </Provider>
        )

        // Verify the checkbox is not displayed
        const checkbox = screen.queryByLabelText('Automatically submit on selection')
        expect(checkbox).not.toBeInTheDocument()
    })

    it('does not show "Automatically submit on selection" checkbox for single choice with open-ended option', () => {
        const singleChoiceWithOpenEndedQuestion: MultipleSurveyQuestion = {
            type: SurveyQuestionType.SingleChoice,
            choices: ['Yes', 'No', 'Other'],
            question: 'Would you recommend our product?',
            description: '',
            buttonText: 'Send Response',
            hasOpenChoice: true,
        }

        useValuesMock.mockImplementation(() => ({
            survey: {
                ...mockSurvey,
                questions: [singleChoiceWithOpenEndedQuestion, mockSurvey.questions[1]],
            },
            descriptionContentType: jest.fn(() => 'text'),
        }))

        render(
            <Provider>
                <SurveyEditQuestionGroup index={0} question={singleChoiceWithOpenEndedQuestion} />
            </Provider>
        )

        // Verify input field is displayed (always visible for open-ended questions)
        const buttonTextInput = screen.getByLabelText('Submit button text')
        expect(buttonTextInput).toBeInTheDocument()

        // Checkbox should not be visible because hasOpenChoice is true
        const checkbox = screen.queryByLabelText('Automatically submit on selection')
        expect(checkbox).not.toBeInTheDocument()
    })
})
