import { useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

import { IconCheck, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { MultiQuestionForm as MultiQuestionFormType } from '~/queries/schema/schema-assistant-messages'

import { maxThreadLogic } from '../maxThreadLogic'
import { MessageTemplate } from './MessageTemplate'
import { multiQuestionFormLogic } from './multiQuestionFormLogic'

interface MultiQuestionFormComponentProps {
    form: MultiQuestionFormType
    isFinal: boolean
    /** Saved answers from the backend (used when the form was previously submitted and page is reloaded) */
    savedAnswers?: Record<string, string>
}

export function MultiQuestionFormComponent({
    form,
    isFinal,
    savedAnswers,
}: MultiQuestionFormComponentProps): JSX.Element | null {
    const { askMax } = useActions(maxThreadLogic)
    const questions = form.questions

    const onSubmit = useCallback(
        (answers: Record<string, string>) => {
            const formattedResponse = questions.map((q) => `${q.question}: ${answers[q.id]}`).join('\n')
            askMax(formattedResponse, false, { form_answers: answers })
        },
        [askMax, questions]
    )

    const logic = multiQuestionFormLogic({ form, onSubmit })
    const { currentQuestionIndex, answers, customInput, showCustomInput, isAnswersSubmitting, isSubmitted } =
        useValues(logic)
    const { selectOption, setShowCustomInput, setCustomInput, submitCustomAnswer } = useActions(logic)

    useEffect(() => {
        function handleKeyDown(event: KeyboardEvent): void {
            if (isAnswersSubmitting || isSubmitted) {
                return
            }
            const options = form.questions[currentQuestionIndex].options
            for (const [index, option] of options.entries()) {
                if (event.key === String(index + 1)) {
                    event.preventDefault()
                    selectOption(option.value)
                    return
                }
            }
            if (event.key === String(options.length + 1)) {
                event.preventDefault()
                setShowCustomInput(true)
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => {
            window.removeEventListener('keydown', handleKeyDown)
        }
    }, [form, selectOption, setShowCustomInput, currentQuestionIndex, isAnswersSubmitting, isSubmitted])

    if (!questions || questions.length === 0) {
        return null
    }
    const currentQuestion = questions[currentQuestionIndex]
    const allowCustomAnswer = currentQuestion.allow_custom_answer !== false

    // If form has been submitted (not final) or all questions answered and submitted, show recap
    // Use savedAnswers from backend if available (for page reloads), otherwise use local answers state
    if (!isFinal || isSubmitted) {
        const displayAnswers = savedAnswers || answers
        return <FormRecap questions={questions} answers={displayAnswers} />
    }

    return (
        <MessageTemplate type="ai" wrapperClassName="w-full">
            <form className="flex flex-col gap-3" aria-label="Multi-question form">
                {/* Progress indicator */}
                {questions.length > 1 && (
                    <div className="flex items-center gap-2 text-xs text-muted">
                        <span>
                            Question {currentQuestionIndex + 1} of {questions.length}
                        </span>
                        <div className="flex gap-1">
                            {questions.map((question, index) => (
                                <div
                                    key={question.id}
                                    className={`w-2 h-2 rounded-full ${
                                        index < currentQuestionIndex
                                            ? 'bg-success'
                                            : index === currentQuestionIndex
                                              ? 'bg-primary'
                                              : 'bg-border'
                                    }`}
                                />
                            ))}
                        </div>
                    </div>
                )}

                {/* Question */}
                <div className="font-medium">{currentQuestion.question}</div>

                {/* Loading state */}
                {isAnswersSubmitting ? (
                    <div className="flex items-center gap-2 text-muted">
                        <Spinner className="size-4" />
                        <span>Submitting answers...</span>
                    </div>
                ) : (
                    /* Options */
                    <div className="flex flex-col gap-1.5">
                        {currentQuestion.options &&
                            currentQuestion.options.map((option, index) => (
                                <div key={option.value} className="flex items-center gap-2">
                                    <div className="text-muted size-4 shrink-0 flex items-center justify-center">
                                        {index + 1}.
                                    </div>
                                    <LemonButton
                                        onClick={() => selectOption(option.value)}
                                        type="secondary"
                                        size="small"
                                        className="justify-start text-wrap w-[calc(100%-2rem)]"
                                    >
                                        {option.value}
                                    </LemonButton>
                                </div>
                            ))}

                        {/* Custom answer option */}
                        {allowCustomAnswer && !showCustomInput && (
                            <div className="flex items-center gap-2">
                                <span className="text-muted size-4 pt-0.5 shrink-0 flex items-center justify-center">
                                    {currentQuestion.options.length + 1}.
                                </span>
                                <LemonButton
                                    onClick={() => setShowCustomInput(true)}
                                    type="tertiary"
                                    size="small"
                                    className="justify-start text-muted w-[calc(100%-2rem)]"
                                    sideIcon={<IconChevronRight />}
                                >
                                    Type your answer
                                </LemonButton>
                            </div>
                        )}

                        {/* Custom input field */}
                        {showCustomInput && (
                            <div className="flex gap-1.5 items-center mt-1">
                                <LemonInput
                                    placeholder="Type your answer..."
                                    fullWidth
                                    value={customInput}
                                    onChange={(newValue) => setCustomInput(newValue)}
                                    onPressEnter={() => submitCustomAnswer()}
                                    autoFocus
                                />
                                <LemonButton
                                    type="primary"
                                    onClick={() => submitCustomAnswer()}
                                    disabledReason={!customInput.trim() ? 'Please type an answer' : undefined}
                                >
                                    Submit
                                </LemonButton>
                                <LemonButton type="tertiary" onClick={() => setShowCustomInput(false)}>
                                    Cancel
                                </LemonButton>
                            </div>
                        )}
                    </div>
                )}
            </form>
        </MessageTemplate>
    )
}

interface FormRecapProps {
    questions: MultiQuestionFormType['questions']
    answers: Record<string, string>
}

function FormRecap({ questions, answers }: FormRecapProps): JSX.Element {
    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    <IconCheck className="text-success" />
                    <span>Form submitted</span>
                </div>
                <div className="flex flex-col gap-1.5">
                    {questions.map((question) => (
                        <div key={question.id} className="text-sm">
                            <span className="text-muted">{question.question}</span>
                            <br />
                            <span className="font-medium">{answers[question.id] || '—'}</span>
                        </div>
                    ))}
                </div>
            </div>
        </MessageTemplate>
    )
}
