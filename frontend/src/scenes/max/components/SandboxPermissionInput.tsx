import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { MarkdownMessage } from '../MarkdownMessage'
import { mapPermissionOptions } from '../sandboxPermissionUtils'
import { sandboxStreamLogic } from '../sandboxStreamLogic'
import type { PermissionRequestRecord } from '../types/sandboxStreamTypes'

interface SandboxPermissionInputProps {
    conversationId: string
    request: PermissionRequestRecord
}

/**
 * Self-contained input-area renderer for an ACP `permission_request` on a sandbox conversation.
 * Owns its own approve/decline buttons (no shared OptionSelector) so it can model the current ACP
 * shape natively: `mapPermissionOptions` classifies each option by prefix (`allow*` approve, else
 * decline), and `allow_always` stays hidden unless a tool preview opts into rememberable decisions.
 * Every option is a one-click button; only the legacy `reject_with_feedback` kind is feedback-only,
 * reachable through the text field.
 *
 * Submitting POSTs through `sandboxStreamLogic.respondToPermission`; the logic's
 * `respondingToPermission` drives the loading/double-submit guard and re-enables the controls when
 * the POST fails (the pending request only clears on success).
 */
export function SandboxPermissionInput({ conversationId, request }: SandboxPermissionInputProps): JSX.Element {
    const boundLogic = sandboxStreamLogic({ conversationId })
    const { respondToPermission } = useActions(boundLogic)
    const { respondingToPermission, currentMode } = useValues(boundLogic)

    const [showFeedback, setShowFeedback] = useState(false)
    const [feedback, setFeedback] = useState('')

    // A request whose every option was filtered out (e.g. only `allow_always` without a rememberable
    // preview) must still be answerable — fall back to showing everything.
    const defaultOptions = mapPermissionOptions(request.options)
    const mappedOptions = defaultOptions.length > 0 ? defaultOptions : mapPermissionOptions(request.options, true)
    // Only the legacy `reject_with_feedback` kind is feedback-only — reachable solely through the
    // text field. A `reject_once` decline is a plain one-click button with no optional-feedback toggle.
    const feedbackOption = mappedOptions.find((o) => o.requiresFeedback)
    // Every option except the legacy feedback-only one renders as a one-click button.
    const buttonOptions = mappedOptions.filter((o) => !o.requiresFeedback)

    // Plan approvals are raised while the agent is in plan mode — the mode is the grounded signal;
    // `toolCall.kind === 'plan'` covers adapters that tag the request directly.
    const isPlan = currentMode === 'plan' || request.rawToolCall.kind === 'plan'

    const respond = (optionId: string): void => {
        if (respondingToPermission) {
            return
        }
        respondToPermission({ conversationId, requestId: request.requestId, optionId })
    }

    const submitFeedback = (): void => {
        const trimmed = feedback.trim()
        if (!feedbackOption || respondingToPermission || !trimmed) {
            return
        }
        respondToPermission({
            conversationId,
            requestId: request.requestId,
            optionId: feedbackOption.optionId,
            customInput: trimmed,
        })
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2 text-sm">
                <IconWarning className="text-warning size-4" />
                <span className="font-medium">{isPlan ? 'Approve this plan?' : 'Approval required'}</span>
            </div>
            {(request.title || request.description) && (
                <div className="max-h-60 overflow-y-auto">
                    <MarkdownMessage
                        content={request.description ?? request.title ?? ''}
                        id={`permission-${request.requestId}`}
                    />
                </div>
            )}
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            {respondingToPermission ? (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner className="size-4" />
                    <span>Sending response...</span>
                </div>
            ) : (
                <div className="flex flex-col gap-1.5">
                    {buttonOptions.map((o) => (
                        <LemonButton
                            key={o.optionId}
                            type={o.primary ? 'primary' : 'secondary'}
                            icon={o.decision === 'approved' ? <IconCheck /> : <IconX />}
                            onClick={() => respond(o.optionId)}
                            fullWidth
                            center
                        >
                            {o.label}
                        </LemonButton>
                    ))}
                    {feedbackOption &&
                        (showFeedback ? (
                            <div className="flex flex-col gap-2">
                                <LemonTextArea
                                    placeholder="Explain what you'd like instead..."
                                    value={feedback}
                                    onChange={setFeedback}
                                    minRows={2}
                                    autoFocus
                                />
                                <div className="flex items-center justify-end gap-2">
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => {
                                            setShowFeedback(false)
                                            setFeedback('')
                                        }}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        disabledReason={!feedback.trim() ? 'Please type a response' : undefined}
                                        onClick={submitFeedback}
                                    >
                                        Send
                                    </LemonButton>
                                </div>
                            </div>
                        ) : (
                            <LemonButton
                                type="tertiary"
                                icon={<IconX />}
                                onClick={() => setShowFeedback(true)}
                                fullWidth
                                center
                            >
                                {feedbackOption.label}
                            </LemonButton>
                        ))}
                </div>
            )}
        </div>
    )
}
