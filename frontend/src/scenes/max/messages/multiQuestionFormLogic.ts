import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { MultiQuestionForm as MultiQuestionFormType } from '~/queries/schema/schema-assistant-messages'

import type { multiQuestionFormLogicType } from './multiQuestionFormLogicType'

export interface MultiQuestionFormLogicProps {
    form: MultiQuestionFormType
    onSubmit: (answers: Record<string, string>) => void
}

export const multiQuestionFormLogic = kea<multiQuestionFormLogicType>([
    path(['scenes', 'max', 'messages', 'multiQuestionFormLogic']),
    props({} as MultiQuestionFormLogicProps),
    key((props) => props.form.questions.map((q: MultiQuestionFormType['questions'][number]) => q.id).join('-')),

    actions({
        selectOption: (value: string) => ({ value }),
        setShowCustomInput: (show: boolean) => ({ show }),
        setCustomInput: (value: string) => ({ value }),
        submitCustomAnswer: true,
        advanceToNextQuestion: true,
        setIsSubmitted: (isSubmitted: boolean) => ({ isSubmitted }),
    }),

    reducers({
        currentQuestionIndex: [
            0,
            {
                advanceToNextQuestion: (state: number) => state + 1,
            },
        ],
        customInput: [
            '',
            {
                setCustomInput: (_: string, { value }) => value,
                selectOption: () => '',
                advanceToNextQuestion: () => '',
            },
        ],
        showCustomInput: [
            false,
            {
                setShowCustomInput: (_: boolean, { show }) => show,
                selectOption: () => false,
                advanceToNextQuestion: () => false,
            },
        ],
        isSubmitted: [
            false,
            {
                setIsSubmitted: (_: boolean, { isSubmitted }) => isSubmitted,
                submitAnswersSuccess: () => true,
            },
        ],
    }),

    forms(({ props }) => ({
        answers: {
            defaults: {} as Record<string, string>,
            submit: (answers) => {
                props.onSubmit(answers)
            },
        },
    })),

    selectors({
        questionsCount: [() => [(_, props) => props.form], (form: MultiQuestionFormType) => form.questions.length],
        isLastQuestion: [
            (s) => [s.currentQuestionIndex, s.questionsCount],
            (currentQuestionIndex: number, questionsCount: number) => currentQuestionIndex >= questionsCount - 1,
        ],
    }),

    listeners(({ props, values, actions }) => ({
        selectOption: ({ value }) => {
            const currentQuestion = props.form.questions[values.currentQuestionIndex]
            const updatedAnswers = { ...values.answers, [currentQuestion.id]: value }
            actions.setAnswersValues(updatedAnswers)

            if (values.isLastQuestion) {
                // Trigger form submission - kea-forms will call the submit handler with the current values
                actions.submitAnswers()
            } else {
                actions.advanceToNextQuestion()
            }
        },
        submitCustomAnswer: () => {
            if (!values.customInput.trim()) {
                return
            }

            const currentQuestion = props.form.questions[values.currentQuestionIndex]
            const trimmedValue = values.customInput.trim()
            const updatedAnswers = { ...values.answers, [currentQuestion.id]: trimmedValue }
            actions.setAnswersValues(updatedAnswers)

            // Clear custom input and hide the input field after capturing the value
            actions.setCustomInput('')
            actions.setShowCustomInput(false)

            if (values.isLastQuestion) {
                // Trigger form submission - kea-forms will call the submit handler with the current values
                actions.submitAnswers()
            } else {
                actions.advanceToNextQuestion()
            }
        },
    })),
])
