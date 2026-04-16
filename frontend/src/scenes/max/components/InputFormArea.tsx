import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTabs, Spinner } from '@posthog/lemon-ui'

import {
    DangerousOperationResponse,
    MultiQuestionForm,
    MultiQuestionFormQuestion,
} from '~/queries/schema/schema-assistant-messages'

import { MarkdownMessage } from '../MarkdownMessage'
import { maxThreadLogic } from '../maxThreadLogic'
import { Option, OptionSelector } from './OptionSelector'
import { MultiFieldQuestion, QuestionField, isFieldValid } from './QuestionField'

function isQuestionComplete(
    q: MultiQuestionFormQuestion,
    answers: Record<string, string | string[]>,
    confirmedQuestions?: Set<string>,
    skippedQuestions?: Set<string>
): boolean {
    if (skippedQuestions?.has(q.id)) {
        return true
    }
    if (q.fields?.length) {
        // Multi_field questions with defaults (toggles, sliders) can appear "valid" on mount.
        // Require the user to explicitly confirm by clicking the submit button.
        if (confirmedQuestions && !confirmedQuestions.has(q.id)) {
            return false
        }
        return q.fields.every((field) => isFieldValid(field, answers[field.id]))
    }
    if (q.type === 'multi_select') {
        // Multi_select questions accumulate selections before submission.
        // Require explicit confirmation like multi_field questions.
        if (!confirmedQuestions?.has(q.id)) {
            return false
        }
        const val = answers[q.id]
        return Array.isArray(val) && val.length > 0
    }
    return answers[q.id] !== undefined
}

function getClearedAnswersForQuestion(
    question: MultiQuestionFormQuestion,
    answers: Record<string, string | string[]>
): Record<string, string | string[]> {
    const nextAnswers = { ...answers }

    if (question.fields?.length) {
        for (const field of question.fields) {
            delete nextAnswers[field.id]
        }
    } else {
        delete nextAnswers[question.id]
    }

    return nextAnswers
}

function removeQuestionFromSet(questionId: string, values: Set<string>): Set<string> {
    if (!values.has(questionId)) {
        return values
    }

    const nextValues = new Set(values)
    nextValues.delete(questionId)
    return nextValues
}

interface MultiQuestionFormInputProps {
    form: MultiQuestionForm
    /** Initial answers for stories/testing */
    initialAnswers?: Record<string, string | string[]>
}

export function MultiQuestionFormInput({ form, initialAnswers = {} }: MultiQuestionFormInputProps): JSX.Element | null {
    const { continueAfterForm, continueAfterFormDismissal } = useActions(maxThreadLogic)
    const questions = form.questions

    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
    // Track which multi_field questions the user has explicitly confirmed
    const [confirmedQuestions, setConfirmedQuestions] = useState<Set<string>>(() => new Set())
    const [skippedQuestions, setSkippedQuestions] = useState<Set<string>>(() => new Set())
    const [answers, setAnswers] = useState<Record<string, string | string[]>>(() => {
        const initial = { ...initialAnswers }
        for (const q of questions) {
            if (!q.fields) {
                continue
            }
            for (const field of q.fields) {
                if (initial[field.id] !== undefined) {
                    continue
                }
                if (field.type === 'toggle') {
                    initial[field.id] = 'false'
                } else if (field.type === 'slider') {
                    initial[field.id] = String(field.min ?? 0)
                }
            }
        }
        return initial
    })
    const [submissionState, setSubmissionState] = useState<'idle' | 'submitting' | 'dismissing'>('idle')

    const answersRef = useRef(answers)
    answersRef.current = answers
    const confirmedQuestionsRef = useRef(confirmedQuestions)
    confirmedQuestionsRef.current = confirmedQuestions
    const skippedQuestionsRef = useRef(skippedQuestions)
    skippedQuestionsRef.current = skippedQuestions

    const currentQuestion = questions[currentQuestionIndex]

    const contentRef = useRef<HTMLDivElement>(null)
    const { height: contentHeight } = useResizeObserver({ ref: contentRef })

    const allQuestionsCompleted = questions.every((q) =>
        isQuestionComplete(q, answers, confirmedQuestions, skippedQuestions)
    )

    const advanceToNextQuestion = useCallback(
        (
            updatedAnswers: Record<string, string | string[]>,
            nextConfirmedQuestions: Set<string> = confirmedQuestionsRef.current,
            nextSkippedQuestions: Set<string> = skippedQuestionsRef.current
        ) => {
            const allCompleted = questions.every((q) =>
                isQuestionComplete(q, updatedAnswers, nextConfirmedQuestions, nextSkippedQuestions)
            )
            if (allCompleted) {
                setSubmissionState('submitting')
                continueAfterForm(updatedAnswers)
            } else {
                const nextIncompleteQuestionIndex = questions.findIndex(
                    (q, index) =>
                        index > currentQuestionIndex &&
                        !isQuestionComplete(q, updatedAnswers, nextConfirmedQuestions, nextSkippedQuestions)
                )

                if (nextIncompleteQuestionIndex !== -1) {
                    setCurrentQuestionIndex(nextIncompleteQuestionIndex)
                    return
                }

                const firstIncompleteQuestionIndex = questions.findIndex(
                    (q) => !isQuestionComplete(q, updatedAnswers, nextConfirmedQuestions, nextSkippedQuestions)
                )
                if (firstIncompleteQuestionIndex !== -1) {
                    setCurrentQuestionIndex(firstIncompleteQuestionIndex)
                }
            }
        },
        [continueAfterForm, currentQuestionIndex, questions]
    )

    const handleSingleFieldAnswer = useCallback(
        (value: string | string[] | null) => {
            const nextSkippedQuestions = removeQuestionFromSet(currentQuestion.id, skippedQuestionsRef.current)
            if (nextSkippedQuestions !== skippedQuestionsRef.current) {
                setSkippedQuestions(nextSkippedQuestions)
                skippedQuestionsRef.current = nextSkippedQuestions
            }

            if (value === null) {
                const updatedAnswers = { ...answersRef.current }
                delete updatedAnswers[currentQuestion.id]
                setAnswers(updatedAnswers)
                answersRef.current = updatedAnswers
                return
            }

            const updatedAnswers = { ...answersRef.current, [currentQuestion.id]: value }
            setAnswers(updatedAnswers)
            advanceToNextQuestion(updatedAnswers, confirmedQuestionsRef.current, nextSkippedQuestions)
        },
        [currentQuestion, advanceToNextQuestion]
    )

    const handleFieldChange = useCallback(
        (fieldId: string, value: string | string[]) => {
            const nextSkippedQuestions = removeQuestionFromSet(currentQuestion.id, skippedQuestionsRef.current)
            if (nextSkippedQuestions !== skippedQuestionsRef.current) {
                setSkippedQuestions(nextSkippedQuestions)
                skippedQuestionsRef.current = nextSkippedQuestions
            }
            setAnswers((prev) => ({ ...prev, [fieldId]: value }))
        },
        [currentQuestion.id]
    )

    const handleMultiSelectChange = useCallback(
        (value: string[]) => {
            const nextSkippedQuestions = removeQuestionFromSet(currentQuestion.id, skippedQuestionsRef.current)
            if (nextSkippedQuestions !== skippedQuestionsRef.current) {
                setSkippedQuestions(nextSkippedQuestions)
                skippedQuestionsRef.current = nextSkippedQuestions
            }
            const nextConfirmedQuestions = removeQuestionFromSet(currentQuestion.id, confirmedQuestionsRef.current)
            if (nextConfirmedQuestions !== confirmedQuestionsRef.current) {
                setConfirmedQuestions(nextConfirmedQuestions)
                confirmedQuestionsRef.current = nextConfirmedQuestions
            }
            const updatedAnswers = { ...answersRef.current, [currentQuestion.id]: value }
            setAnswers(updatedAnswers)
            answersRef.current = updatedAnswers
        },
        [currentQuestion.id]
    )

    const handleMultiFieldSubmit = useCallback(() => {
        const nextConfirmedQuestions = new Set(confirmedQuestionsRef.current)
        nextConfirmedQuestions.add(currentQuestion.id)
        setConfirmedQuestions(nextConfirmedQuestions)
        confirmedQuestionsRef.current = nextConfirmedQuestions

        const nextSkippedQuestions = removeQuestionFromSet(currentQuestion.id, skippedQuestionsRef.current)
        if (nextSkippedQuestions !== skippedQuestionsRef.current) {
            setSkippedQuestions(nextSkippedQuestions)
            skippedQuestionsRef.current = nextSkippedQuestions
        }

        advanceToNextQuestion(answersRef.current, nextConfirmedQuestions, nextSkippedQuestions)
    }, [advanceToNextQuestion, currentQuestion])

    const handleSkipQuestion = useCallback(() => {
        const updatedAnswers = getClearedAnswersForQuestion(currentQuestion, answersRef.current)
        setAnswers(updatedAnswers)

        const nextSkippedQuestions = new Set(skippedQuestionsRef.current)
        nextSkippedQuestions.add(currentQuestion.id)
        setSkippedQuestions(nextSkippedQuestions)
        skippedQuestionsRef.current = nextSkippedQuestions

        const nextConfirmedQuestions = removeQuestionFromSet(currentQuestion.id, confirmedQuestionsRef.current)
        if (nextConfirmedQuestions !== confirmedQuestionsRef.current) {
            setConfirmedQuestions(nextConfirmedQuestions)
            confirmedQuestionsRef.current = nextConfirmedQuestions
        }

        advanceToNextQuestion(updatedAnswers, nextConfirmedQuestions, nextSkippedQuestions)
    }, [advanceToNextQuestion, currentQuestion])

    const handleDismissForm = useCallback(() => {
        setSubmissionState('dismissing')
        continueAfterFormDismissal()
    }, [continueAfterFormDismissal])

    const handleTabClick = useCallback((index: number) => {
        setCurrentQuestionIndex(index)
    }, [])

    if (!currentQuestion || submissionState !== 'idle') {
        return (
            <div className="flex items-center gap-2 text-muted p-3">
                <Spinner className="size-4" />
                <span>{submissionState === 'dismissing' ? 'Dismissing form...' : 'Submitting answers...'}</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            {questions.length > 1 && (
                <LemonTabs
                    size="xsmall"
                    activeKey={currentQuestionIndex}
                    onChange={handleTabClick}
                    tabs={questions.map((question, index) => {
                        return {
                            key: index,
                            label: question.title,
                            completed: isQuestionComplete(question, answers, confirmedQuestions, skippedQuestions),
                        }
                    })}
                    className="w-[calc(100%+var(--spacing-3))] -mx-3 [&>ul]:pl-3 -mt-2.5"
                    rightSlot={
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            onClick={handleDismissForm}
                            aria-label="Dismiss form"
                        />
                    }
                    rightSlotClassName="pr-1 bg-unset"
                />
            )}
            <div
                className="transition-[height] duration-150 motion-reduce:transition-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: contentHeight }}
            >
                <div ref={contentRef}>
                    {questions.map((q, index) => {
                        const active = index === currentQuestionIndex
                        const qIsMultiField = q.type === 'multi_field' || !!(q.fields && q.fields.length > 0)

                        return (
                            <div
                                key={q.id}
                                className={
                                    active
                                        ? 'flex flex-col gap-3 starting:opacity-0 opacity-100 transition-[opacity] duration-150 motion-reduce:transition-none'
                                        : 'hidden'
                                }
                            >
                                <div className="font-medium text-sm">{q.question}</div>
                                {qIsMultiField ? (
                                    <MultiFieldQuestion
                                        question={q}
                                        answers={answers}
                                        onFieldChange={handleFieldChange}
                                        onSubmit={handleMultiFieldSubmit}
                                        onSkip={handleSkipQuestion}
                                        submitLabel={allQuestionsCompleted ? 'Submit' : 'Next'}
                                    />
                                ) : (
                                    <QuestionField
                                        question={q}
                                        value={answers[q.id]}
                                        onAnswer={handleSingleFieldAnswer}
                                        onChange={handleMultiSelectChange}
                                        onSubmit={handleMultiFieldSubmit}
                                        onSkip={handleSkipQuestion}
                                        submitLabel={allQuestionsCompleted ? 'Submit' : 'Next'}
                                    />
                                )}
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}

interface DangerousOperationInputProps {
    operation: DangerousOperationResponse
}

function DangerousOperationInput({ operation }: DangerousOperationInputProps): JSX.Element {
    const { continueAfterApproval, continueAfterRejection } = useActions(maxThreadLogic)
    const [status, setStatus] = useState<'pending' | 'approving' | 'rejecting' | 'custom'>('pending')

    const options: Option[] = [
        { label: 'Approve and execute', value: 'approve', icon: <IconCheck /> },
        { label: 'Reject this operation', value: 'reject', icon: <IconX /> },
    ]

    const handleSelect = (value: string | null): void => {
        if (value === 'approve') {
            setStatus('approving')
            continueAfterApproval(operation.proposalId)
        } else if (value === 'reject') {
            setStatus('rejecting')
            continueAfterRejection(operation.proposalId)
        }
    }

    const handleCustomSubmit = (customResponse: string): void => {
        setStatus('custom')
        continueAfterRejection(operation.proposalId, customResponse)
    }

    const isLoading = status !== 'pending'

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2 text-sm">
                <IconWarning className="text-warning size-4" />
                <span className="font-medium">Approval required</span>
            </div>
            {operation.toolName !== 'finalize_plan' && (
                <p className="text-xs text-secondary m-0">Review the changes below before approving:</p>
            )}
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <div className="max-h-60 overflow-y-auto">
                <MarkdownMessage content={operation.preview} id={`approval-${operation.proposalId}`} />
            </div>
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <OptionSelector
                options={options}
                onSelect={handleSelect}
                allowCustom
                customPlaceholder="Explain what you'd like instead..."
                onCustomSubmit={handleCustomSubmit}
                loading={isLoading}
                loadingMessage={
                    status === 'approving'
                        ? 'Approving...'
                        : status === 'custom'
                          ? 'Sending response...'
                          : 'Rejecting...'
                }
            />
        </div>
    )
}

export function InputFormArea(): JSX.Element | null {
    // Use raw state values instead of selector to ensure re-renders on state changes
    const { activeMultiQuestionForm, pendingApprovalProposalId, pendingApprovalsData, resolvedApprovalStatuses } =
        useValues(maxThreadLogic)

    // Build the approval object to display - only show if not yet resolved
    // Resolved approvals are shown as summaries in the chat thread, not in the input area
    const activeDangerousOperationApproval = useMemo(() => {
        if (!pendingApprovalProposalId) {
            return null
        }
        // Don't show if already resolved - the summary will appear in the chat thread
        if (resolvedApprovalStatuses[pendingApprovalProposalId]) {
            return null
        }
        const approval = pendingApprovalsData[pendingApprovalProposalId]
        if (!approval) {
            return null
        }
        return {
            status: 'pending_approval' as const,
            proposalId: approval.proposal_id,
            toolName: approval.tool_name,
            preview: approval.preview,
            payload: approval.payload as Record<string, unknown>,
        }
    }, [pendingApprovalProposalId, pendingApprovalsData, resolvedApprovalStatuses])

    if (activeDangerousOperationApproval) {
        return (
            <DangerousOperationInput
                key={activeDangerousOperationApproval.proposalId}
                operation={activeDangerousOperationApproval}
            />
        )
    }

    if (activeMultiQuestionForm) {
        return <MultiQuestionFormInput form={activeMultiQuestionForm} />
    }

    return null
}
