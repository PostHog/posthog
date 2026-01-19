import { expectLogic } from 'kea-test-utils'

import { MultiQuestionForm } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'

import { multiQuestionFormLogic } from './multiQuestionFormLogic'

const createMockForm = (questionCount: number): MultiQuestionForm => ({
    questions: Array.from({ length: questionCount }, (_, i) => ({
        id: `q${i + 1}`,
        question: `Question ${i + 1}?`,
        options: [{ value: 'Option A' }, { value: 'Option B' }],
        allow_custom_answer: true,
    })),
})

describe('multiQuestionFormLogic', () => {
    let onSubmit: jest.Mock

    beforeEach(() => {
        initKeaTests()
        onSubmit = jest.fn()
    })

    describe('selectOption', () => {
        it('advances to next question when not on last question', async () => {
            const form = createMockForm(2)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectOption('Option A')
            })
                .toDispatchActions(['selectOption', 'setAnswersValues', 'advanceToNextQuestion'])
                .toMatchValues({
                    currentQuestionIndex: 1,
                    answers: { q1: 'Option A' },
                })

            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('submits form when on last question', async () => {
            const form = createMockForm(1)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.selectOption('Option B')
            })
                .toDispatchActions(['selectOption', 'setAnswersValues', 'submitAnswers'])
                .toMatchValues({
                    answers: { q1: 'Option B' },
                })

            expect(onSubmit).toHaveBeenCalledWith({ q1: 'Option B' })
        })

        it('clears custom input when option is selected', async () => {
            const form = createMockForm(2)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            logic.actions.setCustomInput('some text')
            logic.actions.setShowCustomInput(true)

            await expectLogic(logic).toMatchValues({
                customInput: 'some text',
                showCustomInput: true,
            })

            await expectLogic(logic, () => {
                logic.actions.selectOption('Option A')
            }).toMatchValues({
                customInput: '',
                showCustomInput: false,
            })
        })
    })

    describe('submitCustomAnswer', () => {
        it('does nothing when custom input is empty', async () => {
            const form = createMockForm(1)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            logic.actions.setCustomInput('')

            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            })
                .toDispatchActions(['submitCustomAnswer'])
                .toNotHaveDispatchedActions(['setAnswersValues', 'submitAnswers'])

            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('does nothing when custom input is only whitespace', async () => {
            const form = createMockForm(1)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            logic.actions.setCustomInput('   ')

            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            })
                .toDispatchActions(['submitCustomAnswer'])
                .toNotHaveDispatchedActions(['setAnswersValues', 'submitAnswers'])

            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('submits custom answer and advances to next question when not on last question', async () => {
            const form = createMockForm(2)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            logic.actions.setCustomInput('My custom answer')
            logic.actions.setShowCustomInput(true)

            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            })
                .toDispatchActions([
                    'submitCustomAnswer',
                    'setAnswersValues',
                    'setCustomInput',
                    'setShowCustomInput',
                    'advanceToNextQuestion',
                ])
                .toMatchValues({
                    currentQuestionIndex: 1,
                    answers: { q1: 'My custom answer' },
                    customInput: '',
                    showCustomInput: false,
                })

            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('submits custom answer and submits form when on last question', async () => {
            const form = createMockForm(1)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            logic.actions.setCustomInput('My custom answer')
            logic.actions.setShowCustomInput(true)

            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            })
                .toDispatchActions([
                    'submitCustomAnswer',
                    'setAnswersValues',
                    'setCustomInput',
                    'setShowCustomInput',
                    'submitAnswers',
                ])
                .toMatchValues({
                    answers: { q1: 'My custom answer' },
                    customInput: '',
                    showCustomInput: false,
                })

            expect(onSubmit).toHaveBeenCalledWith({ q1: 'My custom answer' })
        })

        it('trims whitespace from custom answer', async () => {
            const form = createMockForm(1)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            logic.actions.setCustomInput('  trimmed answer  ')

            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            }).toMatchValues({
                answers: { q1: 'trimmed answer' },
            })

            expect(onSubmit).toHaveBeenCalledWith({ q1: 'trimmed answer' })
        })
    })

    describe('multi-question flow', () => {
        it('handles mixed option and custom answers across questions', async () => {
            const form = createMockForm(3)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            // Answer first question with an option
            await expectLogic(logic, () => {
                logic.actions.selectOption('Option A')
            }).toMatchValues({
                currentQuestionIndex: 1,
                answers: { q1: 'Option A' },
            })

            // Answer second question with custom input
            logic.actions.setCustomInput('Custom for Q2')
            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            }).toMatchValues({
                currentQuestionIndex: 2,
                answers: { q1: 'Option A', q2: 'Custom for Q2' },
            })

            // Answer third (last) question with an option - should submit
            await expectLogic(logic, () => {
                logic.actions.selectOption('Option B')
            }).toMatchValues({
                answers: { q1: 'Option A', q2: 'Custom for Q2', q3: 'Option B' },
            })

            expect(onSubmit).toHaveBeenCalledWith({
                q1: 'Option A',
                q2: 'Custom for Q2',
                q3: 'Option B',
            })
        })

        it('submits form with custom answer on last question', async () => {
            const form = createMockForm(2)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            // Answer first question
            logic.actions.selectOption('Option A')

            // Answer last question with custom input
            logic.actions.setCustomInput('Final custom answer')
            await expectLogic(logic, () => {
                logic.actions.submitCustomAnswer()
            }).toMatchValues({
                answers: { q1: 'Option A', q2: 'Final custom answer' },
            })

            expect(onSubmit).toHaveBeenCalledWith({
                q1: 'Option A',
                q2: 'Final custom answer',
            })
        })
    })

    describe('selectors', () => {
        it('questionsCount returns correct count', async () => {
            const form = createMockForm(3)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                questionsCount: 3,
            })
        })

        it.each([
            [3, 0, false],
            [3, 1, false],
            [3, 2, true],
            [1, 0, true],
        ])('isLastQuestion with %i questions at index %i is %s', async (questionCount, index, expected) => {
            const form = createMockForm(questionCount)
            const logic = multiQuestionFormLogic({ form, onSubmit })
            logic.mount()

            // Advance to the target index
            for (let i = 0; i < index; i++) {
                logic.actions.selectOption('Option A')
            }

            await expectLogic(logic).toMatchValues({
                currentQuestionIndex: index,
                isLastQuestion: expected,
            })
        })
    })
})
