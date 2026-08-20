import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { OTHER_REASON_MAX_LENGTH, PhaiLegacyNudgeReason } from '../logics/phaiLegacyNudgeLogic'

// Matches the chat column on `/ai`, which `Thread` and `SidebarQuestionInput` both set to `max-w-180`
// centered. In the side panel the max-width never binds, so the banner just fills the panel.
const CHAT_COLUMN = 'w-full max-w-180 self-center mx-auto px-3 pt-3'

const REASON_OPTIONS: { reason: PhaiLegacyNudgeReason; label: string }[] = [
    { reason: 'too_slow', label: 'Too slow' },
    { reason: 'missing_chats', label: 'Missing my chats' },
    { reason: 'broke', label: 'Something broke' },
    { reason: 'worse_answers', label: 'Worse answers' },
]

export interface PhaiLegacyNudgeBannerProps {
    /** `offer` invites the user into the new PostHog AI; `reason` asks why they left it. */
    mode: 'offer' | 'reason'
    /** Whether the legacy thread has a question worth carrying across, which changes what the offer promises. */
    hasQuestion: boolean
    /** Whether the user picked "Other", which replaces the fixed answers with the text field. */
    otherReasonSelected: boolean
    otherReasonText: string
    onAccept: () => void
    onDismiss: () => void
    onSubmitReason: (reason: PhaiLegacyNudgeReason) => void
    onSelectOtherReason: () => void
    onChangeOtherReasonText: (text: string) => void
    onSubmitOtherReason: () => void
}

/**
 * The notice a user who switched back to the legacy chat sees. Plain props so its states stay renderable
 * without the thread machinery behind them; `MaybePhaiLegacyNudge` decides when it appears.
 *
 * Temporary migration affordance - delete alongside `scenes/max` once everyone is on the new PostHog AI.
 */
export function PhaiLegacyNudgeBanner({
    mode,
    hasQuestion,
    otherReasonSelected,
    otherReasonText,
    onAccept,
    onDismiss,
    onSubmitReason,
    onSelectOtherReason,
    onChangeOtherReasonText,
    onSubmitOtherReason,
}: PhaiLegacyNudgeBannerProps): JSX.Element {
    if (mode === 'reason') {
        const canSendOtherReason = !!otherReasonText.trim()

        return (
            <div className={CHAT_COLUMN}>
                <LemonBanner type="ai" onClose={onDismiss}>
                    {otherReasonSelected ? (
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonInput
                                className="grow"
                                size="xsmall"
                                autoFocus
                                value={otherReasonText}
                                onChange={onChangeOtherReasonText}
                                onPressEnter={() => canSendOtherReason && onSubmitOtherReason()}
                                maxLength={OTHER_REASON_MAX_LENGTH}
                                placeholder="What made you switch back?"
                                data-attr="phai-legacy-nudge-reason-other-input"
                            />
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={onSubmitOtherReason}
                                disabledReason={canSendOtherReason ? undefined : 'Write a few words first'}
                                data-attr="phai-legacy-nudge-reason-other-send"
                            >
                                Send
                            </LemonButton>
                        </div>
                    ) : (
                        <div className="flex flex-wrap items-center gap-2">
                            <span>Why did you switch back?</span>
                            {REASON_OPTIONS.map(({ reason, label }) => (
                                <LemonButton
                                    key={reason}
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => onSubmitReason(reason)}
                                    data-attr={`phai-legacy-nudge-reason-${reason}`}
                                >
                                    {label}
                                </LemonButton>
                            ))}
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={onSelectOtherReason}
                                data-attr="phai-legacy-nudge-reason-other"
                            >
                                Other
                            </LemonButton>
                        </div>
                    )}
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className={CHAT_COLUMN}>
            <LemonBanner type="ai" onClose={onDismiss}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                        {hasQuestion ? 'The new PostHog AI can run this for you.' : "You're on the legacy chat."}
                    </span>
                    <LemonButton size="xsmall" type="secondary" onClick={onAccept} data-attr="phai-legacy-nudge-cta">
                        {hasQuestion ? 'Run it' : 'Switch to the new version'}
                    </LemonButton>
                </div>
            </LemonBanner>
        </div>
    )
}
