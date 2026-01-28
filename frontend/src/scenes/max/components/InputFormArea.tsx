import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonDivider, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { DangerousOperationResponse, MultiQuestionForm } from '~/queries/schema/schema-assistant-messages'

import { MarkdownMessage } from '../MarkdownMessage'
import { maxThreadLogic } from '../maxThreadLogic'
import { Option, OptionSelector } from './OptionSelector'

interface MultiQuestionFormInputProps {
    form: MultiQuestionForm
    /** Initial answers for stories/testing */
    initialAnswers?: Record<string, string>
}

function MultiQuestionFormInput({ form, initialAnswers = {} }: MultiQuestionFormInputProps): JSX.Element | null {
    const { continueAfterForm } = useActions(maxThreadLogic)
    const questions = form.questions

    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
    const [answers, setAnswers] = useState<Record<string, string>>(initialAnswers)
    // Track custom input text separately from answers, so switching tabs preserves typed text
    const [customInputs, setCustomInputs] = useState<Record<string, string>>({})
    const [isSubmitting, setIsSubmitting] = useState(false)

    const currentQuestion = questions[currentQuestionIndex]
    const allowCustomAnswer = currentQuestion?.allow_custom_answer !== false
    const isLastQuestion = currentQuestionIndex >= questions.length - 1

    const contentRef = useRef<HTMLDivElement>(null)
    const { height: contentHeight } = useResizeObserver({ ref: contentRef })

    const options: Option[] = useMemo(() => {
        if (!currentQuestion) {
            return []
        }
        return currentQuestion.options.map((option) => ({
            label: option.value,
            value: option.value,
            description: option.description,
        }))
    }, [currentQuestion])

    const allQuestionsAnswered = Object.keys(answers).length === questions.length

    const advanceToNextQuestion = useCallback(
        (updatedAnswers: Record<string, string>) => {
            const allAnswered = Object.keys(updatedAnswers).length === questions.length
            if (allAnswered) {
                setIsSubmitting(true)
                continueAfterForm(updatedAnswers)
            } else if (isLastQuestion) {
                const firstMissingQuestion = questions.find((question) => !updatedAnswers[question.id])
                if (firstMissingQuestion) {
                    setCurrentQuestionIndex(questions.indexOf(firstMissingQuestion))
                }
            } else {
                setCurrentQuestionIndex((prev) => prev + 1)
            }
        },
        [isLastQuestion, questions, continueAfterForm]
    )

    const handleSelect = useCallback(
        (value: string) => {
            const updatedAnswers = { ...answers, [currentQuestion.id]: value }
            setAnswers(updatedAnswers)
            advanceToNextQuestion(updatedAnswers)
        },
        [answers, currentQuestion, advanceToNextQuestion]
    )

    const handleCustomSubmit = useCallback(
        (value: string) => {
            // Store the custom input text and use it as the answer
            setCustomInputs((prev) => ({ ...prev, [currentQuestion.id]: value }))
            const updatedAnswers = { ...answers, [currentQuestion.id]: value }
            setAnswers(updatedAnswers)
            advanceToNextQuestion(updatedAnswers)
        },
        [answers, currentQuestion, advanceToNextQuestion]
    )

    const handleTabClick = useCallback((index: number) => {
        setCurrentQuestionIndex(index)
    }, [])

    if (!currentQuestion || isSubmitting) {
        return (
            <div className="flex items-center gap-2 text-muted p-3">
                <Spinner className="size-4" />
                <span>Submitting answers...</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            {questions.length > 1 && (
                <div className="w-full">
                    <LemonTabs
                        size="xsmall"
                        activeKey={currentQuestionIndex}
                        onChange={handleTabClick}
                        tabs={questions.map((question, index) => {
                            return {
                                key: index,
                                label: question.title,
                                completed: answers[question.id] !== undefined,
                            }
                        })}
                        className="w-[calc(100%+var(--spacing-3))] -mx-3 [&>ul]:pl-3 -mt-2.5"
                    />
                </div>
            )}
            <div
                className="transition-[height] duration-150 motion-reduce:transition-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: contentHeight }}
            >
                <div ref={contentRef}>
                    <div
                        key={currentQuestion.id}
                        className="flex flex-col gap-3 starting:opacity-0 opacity-100 transition-[opacity] duration-150 motion-reduce:transition-none"
                    >
                        <div className="font-medium text-sm">{currentQuestion.question}</div>
                        <OptionSelector
                            options={options}
                            onSelect={handleSelect}
                            allowCustom={allowCustomAnswer}
                            customPlaceholder="Type your answer..."
                            onCustomSubmit={handleCustomSubmit}
                            initialCustomValue={customInputs[currentQuestion.id]}
                            selectedValue={answers[currentQuestion.id]}
                            submitLabel={allQuestionsAnswered ? 'Submit' : 'Next'}
                        />
                    </div>
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

    const handleSelect = (value: string): void => {
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
                <p className="text-xs text-secondary m-0">This operation will make the following changes:</p>
            )}
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <MarkdownMessage content={operation.preview} id={`approval-${operation.proposalId}`} />
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <OptionSelector
                options={options}
                onSelect={handleSelect}
                allowCustom
                customPlaceholder="Type something..."
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
