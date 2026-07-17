import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { MailHog } from 'lib/components/hedgehogs'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { userLogic } from 'scenes/userLogic'

import { onboardingExitLogic } from './onboardingExitLogic'

// Keep in sync with `OrganizationInviteDelegateSerializer.message.max_length` on the backend
// (posthog/api/organization_invite.py). Client-side limit mirrors the server cap so users
// see the constraint as they type instead of after submit.
const MESSAGE_MAX_LENGTH = 1000

export function shouldSubmitDelegate(isComposing: boolean): boolean {
    return !isComposing
}

export function OnboardingExitModal(): JSX.Element {
    const { isExitModalOpen, targetEmail, message, canSubmitDelegation, isSubmitting } = useValues(onboardingExitLogic)
    const { closeExitModal, setTargetEmail, setMessage, submitDelegation } = useActions(onboardingExitLogic)
    const { user } = useValues(userLogic)

    // Track IME composition on the email input. SubmitEvent doesn't carry `isComposing`, so
    // we watch composition events directly — otherwise CJK users pressing Enter to confirm
    // a character would submit the form mid-composition.
    const isComposingRef = useRef(false)

    const onDelegateSubmit = (e: React.FormEvent): void => {
        e.preventDefault()
        if (!shouldSubmitDelegate(isComposingRef.current)) {
            return
        }
        submitDelegation()
    }

    // Always allow close: the listener guards against double-submit, and trapping the user
    // in the modal when a request hangs (slow flag check, 504, network glitch) leaves them
    // with no recovery short of a hard reload.
    const handleClose = (): void => {
        closeExitModal()
    }

    // Defer the danger state until the user has at least blurred the field once.
    // Showing the error after the very first character is hostile; the disabled submit
    // button already communicates the constraint while they're still typing.
    const [emailWasBlurred, setEmailWasBlurred] = useState(false)
    const showEmailValidationError = emailWasBlurred && targetEmail.length > 0 && !canSubmitDelegation

    const senderName = user?.first_name?.trim() || 'Your teammate'
    const orgName = user?.organization?.name?.trim() || 'your team'
    const recipientDisplay = targetEmail.trim() || 'their email'
    // The placeholder text in the textarea must NOT be reflected as live preview content,
    // or users assume the placeholder copy will be sent verbatim. Show it as quoted only
    // when the user has actually typed something.
    const trimmedMessage = message.trim()
    const hasMessage = trimmedMessage.length > 0

    return (
        <LemonModal
            isOpen={isExitModalOpen}
            onClose={handleClose}
            // Treat any typed input as unsaved so an accidental overlay click doesn't silently
            // discard a partially-composed delegation invite.
            hasUnsavedInput={Boolean(targetEmail || message)}
            maxWidth={720}
            title="Hand off setup to a teammate"
            description="We'll invite them as an admin and skip the rest of setup for you."
        >
            <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-6 md:gap-10">
                <form onSubmit={onDelegateSubmit} className="flex flex-col gap-2" data-attr="onboarding-exit-modal">
                    <label className="font-semibold" htmlFor="onboarding-exit-email">
                        Teammate's email
                    </label>
                    <LemonInput
                        id="onboarding-exit-email"
                        type="email"
                        autoFocus
                        value={targetEmail}
                        onChange={setTargetEmail}
                        status={showEmailValidationError ? 'danger' : 'default'}
                        placeholder="engineer@example.com"
                        data-attr="onboarding-exit-email-input"
                        aria-describedby={showEmailValidationError ? 'onboarding-exit-email-error' : undefined}
                        aria-invalid={showEmailValidationError || undefined}
                        onKeyDown={(e) => {
                            // KeyboardEvent.isComposing is the right place to read IME state —
                            // SubmitEvent doesn't carry it. Tracking here so the form submit
                            // handler can skip while the user is mid-composition.
                            isComposingRef.current = (e.nativeEvent as KeyboardEvent).isComposing
                        }}
                        onKeyUp={(e) => {
                            // Ensure composition state clears after IME confirmation.
                            isComposingRef.current = (e.nativeEvent as KeyboardEvent).isComposing
                        }}
                        onBlur={() => {
                            isComposingRef.current = false
                            setEmailWasBlurred(true)
                        }}
                    />
                    {showEmailValidationError ? (
                        <p id="onboarding-exit-email-error" className="m-0 text-xs text-danger">
                            Enter a valid email address
                        </p>
                    ) : null}
                    <label className="font-semibold mt-2" htmlFor="onboarding-exit-message">
                        Personal message (optional)
                    </label>
                    <LemonTextArea
                        id="onboarding-exit-message"
                        value={message}
                        onChange={setMessage}
                        placeholder="Hey — can you get this set up? Thanks!"
                        data-attr="onboarding-exit-message-input"
                        minRows={3}
                        maxLength={MESSAGE_MAX_LENGTH}
                    />
                    <div className="flex items-start justify-between gap-2 mt-1">
                        <p className="text-secondary text-xs m-0">
                            They'll be added as an admin so they can finish setting up PostHog.
                        </p>
                        <p
                            className={
                                message.length >= MESSAGE_MAX_LENGTH
                                    ? 'text-danger text-xs m-0 shrink-0'
                                    : 'text-muted text-xs m-0 shrink-0'
                            }
                            aria-live="polite"
                        >
                            {message.length}/{MESSAGE_MAX_LENGTH}
                        </p>
                    </div>
                    <div className="flex justify-end gap-2 mt-2">
                        <LemonButton
                            type="secondary"
                            onClick={handleClose}
                            htmlType="button"
                            // Stay enabled during submit to match the "always allow close"
                            // policy enforced by `handleClose` and `hasUnsavedInput`.
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isSubmitting}
                            disabledReason={!canSubmitDelegation ? 'Enter a valid email address' : undefined}
                            data-attr="onboarding-exit-send-invitation"
                        >
                            Send invitation
                        </LemonButton>
                    </div>
                </form>

                {/* Live invitation preview — renders what the teammate will receive. */}
                {/* Preview is hidden below md: — on small viewports the form fills the screen
                    and the preview ends up below the fold, so users can't see it while typing
                    anyway. Skipping it avoids a useless scroll-down step on mobile. */}
                <div className="hidden md:flex flex-col gap-2">
                    <p className="m-0 text-xs text-muted uppercase tracking-wide font-semibold">Preview</p>
                    <div className="rounded-lg border border-primary bg-surface-primary overflow-hidden">
                        <div className="flex items-center gap-2 px-3 py-2 border-b border-primary bg-surface-secondary">
                            <MailHog className="w-8 h-6 object-contain shrink-0" />
                            <span className="text-xs font-semibold">PostHog invitation</span>
                        </div>
                        <div className="p-3 flex flex-col gap-2">
                            <p className="m-0 text-xs text-muted">To: {recipientDisplay}</p>
                            {/* Match the real email's H1 (see posthog/templates/email/delegation_invite.html)
                                so the live preview reflects what the recipient will actually see. */}
                            <p className="m-0 text-sm font-semibold">
                                {senderName} asked you to finish setting up PostHog for {orgName}
                            </p>
                            {hasMessage ? (
                                <div className="rounded bg-surface-secondary px-2 py-2 text-xs italic text-default whitespace-pre-line">
                                    “{trimmedMessage}”
                                </div>
                            ) : (
                                <div className="rounded bg-surface-secondary px-2 py-2 text-xs italic text-muted">
                                    No personal message
                                </div>
                            )}
                            <p className="m-0 text-xs text-muted">
                                You'll be added as an admin so you can finish setup.
                            </p>
                            <LemonButton
                                type="primary"
                                size="small"
                                disabledReason="Preview only"
                                sideIcon={<IconArrowRight />}
                                fullWidth
                            >
                                Accept invitation
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
