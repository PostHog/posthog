import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { Composer, ComposerModelEffortPickers, QueuedMessageList } from 'products/posthog_ai/frontend/api/primitives'

import { Intro } from '../Intro'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { SandboxComposerSurfaces, Thread } from '../Thread'
import { InputFormArea } from './InputFormArea'
import { ThreadAutoScroller } from './ThreadAutoScroller'

/**
 * The new (sandbox) PostHog AI chat for the side panel: renders Max's `Thread` (which already handles all
 * three conversation shapes — born-sandbox, converted, and pure legacy) plus a composer wired to Max's
 * conversation send (`askMax`). A pending approval/question/sandbox-permission request replaces the
 * composer with `InputFormArea`, mirroring `SidebarQuestionInput`. Must render inside Max's `maxLogic` +
 * `maxThreadLogic` binds (it reads/sends through them).
 */
export function PhaiSidePanelChat(): JSX.Element {
    const { threadVisible } = useValues(maxLogic)
    const {
        threadLoading,
        streamingActive,
        activeMultiQuestionForm,
        pendingApprovalProposalId,
        pendingApprovalsData,
        resolvedApprovalStatuses,
        pendingSandboxPermissionRequest,
        queuedMessages,
        queueingEnabled,
        sandboxModel,
        sandboxEffort,
    } = useValues(maxThreadLogic)
    const { askMax, stopGeneration, updateQueuedMessage, deleteQueuedMessage, setSandboxModel, setSandboxEffort } =
        useActions(maxThreadLogic)

    // A pending sandbox request only originates from the sandbox stream, so its presence alone is
    // enough — gating on `agent_runtime` would strand approvals on as-yet-unresolved conversations.
    const hasSandboxPermissionToShow = !!pendingSandboxPermissionRequest

    // Check if there's a pending (not yet resolved) approval to show
    const hasApprovalToShow = useMemo(() => {
        if (!pendingApprovalProposalId) {
            return false
        }
        // Don't show if already resolved - resolved approvals appear as summaries in the chat thread
        if (resolvedApprovalStatuses[pendingApprovalProposalId]) {
            return false
        }
        return !!pendingApprovalsData[pendingApprovalProposalId]
    }, [pendingApprovalProposalId, pendingApprovalsData, resolvedApprovalStatuses])

    const showFormArea = activeMultiQuestionForm || hasApprovalToShow || hasSandboxPermissionToShow

    // Local draft so each keystroke is a cheap local re-render rather than a global kea dispatch — long
    // threads make per-keystroke store notifications expensive (see QuestionInput). `askMax` reads the
    // prompt directly, so kea's `question` doesn't need to hold the draft here.
    const [draft, setDraft] = useState('')

    const submit = (): void => {
        const prompt = draft.trim()
        if (!prompt) {
            return
        }
        askMax(prompt)
        setDraft('')
    }

    return (
        <div className="@container/thread flex flex-col h-full min-h-0">
            {threadVisible ? (
                <div className="flex-1 min-h-0 overflow-y-auto">
                    <ThreadAutoScroller>
                        <Thread className="p-1" />
                    </ThreadAutoScroller>
                </div>
            ) : (
                <div className="flex flex-1 min-h-0 flex-col items-center justify-center gap-3 px-3 overflow-y-auto">
                    <Intro />
                </div>
            )}
            <SandboxComposerSurfaces />
            <div className="border-t border-primary px-3 pb-3 pt-2">
                <div className="mx-auto w-full max-w-180">
                    {showFormArea ? (
                        <div className="border border-primary rounded-lg bg-surface-primary">
                            <InputFormArea />
                        </div>
                    ) : (
                        <Composer.Root
                            value={draft}
                            onChange={setDraft}
                            onSubmit={submit}
                            loading={threadLoading}
                            isTurnActive={streamingActive}
                            onStop={() => stopGeneration()}
                        >
                            {queueingEnabled && queuedMessages.length > 0 && (
                                <Composer.Banner>
                                    <QueuedMessageList
                                        messages={queuedMessages}
                                        onUpdate={updateQueuedMessage}
                                        onRemove={deleteQueuedMessage}
                                    />
                                </Composer.Banner>
                            )}
                            <Composer.Frame ringActive={!streamingActive}>
                                <Composer.Field>
                                    <Composer.Placeholder>Ask PostHog AI…</Composer.Placeholder>
                                    <Composer.Textarea data-attr="phai-sidepanel-composer" />
                                </Composer.Field>
                                <Composer.Footer>
                                    {/* Model/effort picker: selection lives in maxThreadLogic and is applied
                                    when the message is sent — the backend uses it only when that send starts
                                    a new sandbox run. */}
                                    <ComposerModelEffortPickers
                                        selectedModel={sandboxModel}
                                        selectedEffort={sandboxEffort}
                                        onModelChange={setSandboxModel}
                                        onEffortChange={setSandboxEffort}
                                    />
                                </Composer.Footer>
                            </Composer.Frame>
                            <Composer.Submit data-attr="phai-sidepanel-send" />
                        </Composer.Root>
                    )}
                </div>
            </div>
        </div>
    )
}
