import { useValues } from 'kea'
import { Suspense, useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { maxThreadLogic } from '../maxThreadLogic'

// These forms render only while the agent waits for an answer. Loading them lazily keeps the
// posthog_ai primitives barrel off the eager path of every page that shows the input box.
const MultiQuestionFormInput = lazyWithRetry(() =>
    import('./MultiQuestionFormInput').then((m) => ({ default: m.MultiQuestionFormInput }))
)
const DangerousOperationInput = lazyWithRetry(() =>
    import('./DangerousOperationInput').then((m) => ({ default: m.DangerousOperationInput }))
)
const QuestionInput = lazyWithRetry(() =>
    import('products/posthog_ai/frontend/api/primitives').then((m) => ({ default: m.QuestionInput }))
)
const PermissionInput = lazyWithRetry(() =>
    import('products/posthog_ai/frontend/api/primitives').then((m) => ({ default: m.PermissionInput }))
)

/**
 * Compact badge showing the active ACP permission mode (e.g. plan vs default) for sandbox
 * conversations. Hidden when no mode has been reported. Reads the mode via `maxThreadLogic`'s
 * alias — this renders outside ThreadView's BindLogic subtree, so it cannot bind the keyed
 * stream logic itself.
 */
export function SandboxModeBadge(): JSX.Element | null {
    const { conversation, sandboxCurrentMode } = useValues(maxThreadLogic)

    if (conversation?.agent_runtime !== 'sandbox' || !sandboxCurrentMode) {
        return null
    }

    const isPlan = sandboxCurrentMode === 'plan'
    return (
        <LemonTag size="small" type={isPlan ? 'highlight' : 'muted'}>
            {isPlan ? 'Plan mode' : 'Default mode'}
        </LemonTag>
    )
}

export function InputFormArea(): JSX.Element {
    return (
        <Suspense fallback={null}>
            <ActiveInputForm />
        </Suspense>
    )
}

function ActiveInputForm(): JSX.Element | null {
    // Use raw state values instead of selector to ensure re-renders on state changes
    const {
        activeMultiQuestionForm,
        pendingApprovalProposalId,
        pendingApprovalsData,
        resolvedApprovalStatuses,
        sandboxConversationKey,
        pendingSandboxPermissionRequest,
    } = useValues(maxThreadLogic)

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

    // Sandbox permission requests take precedence in the input area, mirroring the LangGraph
    // dangerous-operation flow but driven by runStreamLogic. A pending request only ever
    // originates from the sandbox stream, so its presence is sufficient — gating on `agent_runtime`
    // would strand approvals on new conversations whose runtime isn't resolved yet.
    if (pendingSandboxPermissionRequest) {
        // An `AskUserQuestion` rides the same permission rails but is a question, not an approval —
        // render the interactive question overlay instead of the approve/decline card.
        if (pendingSandboxPermissionRequest.questions?.length) {
            return (
                <QuestionInput
                    key={pendingSandboxPermissionRequest.requestId}
                    streamKey={sandboxConversationKey}
                    request={pendingSandboxPermissionRequest}
                />
            )
        }
        return (
            <PermissionInput
                key={pendingSandboxPermissionRequest.requestId}
                streamKey={sandboxConversationKey}
                request={pendingSandboxPermissionRequest}
            />
        )
    }

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
