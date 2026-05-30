import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconNotebook, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { MarkdownMessage } from './MarkdownMessage'
import { maxThreadLogic } from './maxThreadLogic'
import { PermissionOption } from './types/sandboxStreamTypes'

/**
 * Which runtime this card renders for. Defaults to `langgraph` so the existing in-thread summary
 * behavior is unchanged for LangGraph conversations (zero-change default). The two sandbox variants
 * layer the interactive ACP permission affordances on top of the same card (03_RICH_UI §9 — the
 * 3-value naming, reconciling the §5.3 2-value `dangerous_operation | plan_approval` set):
 * - `sandbox-permission` — a tool permission request (4 ACP option kinds → buttons + feedback input).
 * - `sandbox-plan` — a finalized-plan approval; same options/resolution/styling, swapped title/icon/body.
 */
export type ApprovalCardVariant = 'langgraph' | 'sandbox-permission' | 'sandbox-plan'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
    /** Defaults to `langgraph` — the existing summary-only behavior, untouched. */
    variant?: ApprovalCardVariant
}

/** Pull the ACP options[] stashed on the merged approval payload at ingest (approvalOperationUtils). */
function readOptions(payload: Record<string, unknown> | undefined): PermissionOption[] {
    const options = payload?.options
    return Array.isArray(options) ? (options as PermissionOption[]) : []
}

/**
 * In-thread approval card. For LangGraph (the default `variant`) it stays a compact status summary —
 * the interaction happens in the input area (DangerousOperationInput). For the sandbox runtime an
 * unresolved request renders the interactive ACP affordances inline, mapping the four option kinds
 * (allow_once / allow_always / reject / reject_with_feedback) to buttons + a feedback input. Once
 * resolved every variant collapses back to the same status summary. See 03_RICH_UI §5.
 */
export function DangerousOperationApprovalCard({
    operation,
    variant = 'langgraph',
}: DangerousOperationApprovalCardProps): JSX.Element {
    // Read both resolvedApprovalStatuses (frontend) and pendingApprovalsData (backend)
    // to ensure we show correct status for both new and historical approvals
    const { resolvedApprovalStatuses, pendingApprovalsData, isSharedThread } = useValues(maxThreadLogic)
    const { continueAfterApproval, continueAfterRejection } = useActions(maxThreadLogic)

    // Local view state for the in-flight decision + the reject-with-feedback text input. The
    // resolution business logic lives in maxThreadLogic (kea) — this only tracks the card's UI.
    const [pendingDecision, setPendingDecision] = useState<'approve' | 'always' | 'reject' | null>(null)
    const [feedbackOpen, setFeedbackOpen] = useState(false)
    const [feedback, setFeedback] = useState('')

    // Frontend resolved status takes precedence over backend status
    const frontendResolved = resolvedApprovalStatuses[operation.proposalId]
    const backendData = pendingApprovalsData[operation.proposalId]
    const backendStatus = backendData?.decision_status

    // Determine the effective status and feedback
    const resolvedStatus = frontendResolved?.status ?? (backendStatus !== 'pending' ? backendStatus : undefined)
    const resolvedFeedback = frontendResolved?.feedback

    const subject = isSharedThread ? 'User' : 'You'
    const isPlan = variant === 'sandbox-plan'
    const isSandbox = variant === 'sandbox-permission' || isPlan
    const PendingIcon = isPlan ? IconNotebook : IconWarning

    // Sandbox runtime + still pending → render the interactive ACP affordances inline.
    if (isSandbox && !resolvedStatus) {
        const options = readOptions(backendData?.payload)
        // allow_always is only offered when the request carries remember:true (03_RICH_UI §5.2).
        const showAlwaysAllow =
            backendData?.payload?.remember === true && options.some((o) => o.kind === 'allow_always')
        const canRejectWithFeedback = options.some((o) => o.kind === 'reject_with_feedback')
        const isResolving = pendingDecision !== null

        const handleApprove = (remember: boolean): void => {
            setPendingDecision(remember ? 'always' : 'approve')
            continueAfterApproval(operation.proposalId, remember)
        }
        const handleReject = (): void => {
            setPendingDecision('reject')
            continueAfterRejection(operation.proposalId)
        }
        const handleFeedbackSubmit = (): void => {
            if (!feedback.trim()) {
                return
            }
            setPendingDecision('reject')
            continueAfterRejection(operation.proposalId, feedback.trim())
        }

        return (
            <div className="flex flex-col gap-2 text-xs">
                <div className="flex items-center gap-1.5">
                    <PendingIcon className="text-warning size-4 flex-shrink-0" />
                    <span className="font-medium text-sm">
                        {isPlan ? 'Approve this plan?' : 'Approve this action?'}
                    </span>
                </div>
                {operation.preview && (
                    <div className="max-h-60 overflow-y-auto">
                        <MarkdownMessage content={operation.preview} id={`approval-${operation.proposalId}`} />
                    </div>
                )}
                {feedbackOpen ? (
                    <div className="flex flex-col gap-1.5">
                        <LemonInput
                            placeholder={
                                isPlan ? 'Explain how to refine the plan...' : "Explain what you'd like instead..."
                            }
                            value={feedback}
                            onChange={setFeedback}
                            onPressEnter={handleFeedbackSubmit}
                            size="small"
                            autoFocus
                            disabled={isResolving}
                        />
                        <div className="flex gap-1.5">
                            <LemonButton
                                type="primary"
                                size="xsmall"
                                onClick={handleFeedbackSubmit}
                                loading={isResolving}
                                disabledReason={!feedback.trim() ? 'Please type a response' : undefined}
                            >
                                Send
                            </LemonButton>
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                onClick={() => setFeedbackOpen(false)}
                                disabledReason={isResolving ? 'Sending your response...' : undefined}
                            >
                                Cancel
                            </LemonButton>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-wrap gap-1.5">
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            icon={<IconCheck />}
                            onClick={() => handleApprove(false)}
                            loading={pendingDecision === 'approve'}
                            disabledReason={isResolving && pendingDecision !== 'approve' ? 'Resolving...' : undefined}
                        >
                            {isPlan ? 'Continue with plan' : 'Approve'}
                        </LemonButton>
                        {showAlwaysAllow && (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                onClick={() => handleApprove(true)}
                                loading={pendingDecision === 'always'}
                                disabledReason={
                                    isResolving && pendingDecision !== 'always' ? 'Resolving...' : undefined
                                }
                            >
                                Always allow
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconX />}
                            onClick={handleReject}
                            loading={pendingDecision === 'reject' && !feedbackOpen}
                            disabledReason={isResolving && pendingDecision !== 'reject' ? 'Resolving...' : undefined}
                        >
                            Decline
                        </LemonButton>
                        {canRejectWithFeedback && (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                onClick={() => setFeedbackOpen(true)}
                                disabledReason={isResolving ? 'Resolving...' : undefined}
                            >
                                {isPlan ? 'Refine plan' : 'Decline with feedback…'}
                            </LemonButton>
                        )}
                    </div>
                )}
            </div>
        )
    }

    // Show pending state while waiting for resolution (summary form — LangGraph default + sandbox post-submit).
    if (!resolvedStatus) {
        return (
            <div className="flex text-xs text-muted">
                <div className="flex items-center justify-center size-5">
                    <PendingIcon />
                </div>
                <div className="flex items-center gap-1 flex-1 min-w-0">
                    <span>Awaiting approval...</span>
                    <Spinner className="size-3" />
                </div>
            </div>
        )
    }

    // Show resolved state
    const isApproved = resolvedStatus === 'approved'
    const action = isPlan ? 'plan' : 'operation'
    const text = isApproved
        ? isPlan
            ? `${subject} approved this plan`
            : `${subject} approved and executed this`
        : resolvedStatus === 'auto_rejected'
          ? `Skipped based on ${isSharedThread ? 'user' : 'your'} feedback`
          : resolvedFeedback
            ? `${subject} responded: "${resolvedFeedback}"`
            : `${subject} declined this ${action}`

    return (
        <div className="flex text-xs text-muted">
            <div className="flex items-center justify-center size-5">
                <PendingIcon />
            </div>
            <div className="flex items-center gap-1 flex-1 min-w-0">
                <span>{text}</span>
            </div>
        </div>
    )
}
