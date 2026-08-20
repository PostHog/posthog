import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { PhaiLegacyNudgeReason } from '../logics/phaiLegacyNudgeLogic'

const REASON_OPTIONS: { reason: PhaiLegacyNudgeReason; label: string }[] = [
    { reason: 'too_slow', label: 'Too slow' },
    { reason: 'missing_chats', label: 'Missing my chats' },
    { reason: 'broke', label: 'Something broke' },
    { reason: 'worse_answers', label: 'Worse answers' },
    { reason: 'just_looking', label: 'Just looking' },
]

export interface PhaiLegacyNudgeBannerProps {
    /** `offer` invites the user into the new PostHog AI; `reason` asks why they left it. */
    mode: 'offer' | 'reason'
    /** Whether the legacy thread has a question worth carrying across, which changes what the offer promises. */
    hasQuestion: boolean
    onAccept: () => void
    onDismiss: () => void
    onSubmitReason: (reason: PhaiLegacyNudgeReason) => void
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
    onAccept,
    onDismiss,
    onSubmitReason,
}: PhaiLegacyNudgeBannerProps): JSX.Element {
    if (mode === 'reason') {
        return (
            <div className="px-4 pt-4">
                <LemonBanner type="ai" onClose={onDismiss}>
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
                    </div>
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="px-4 pt-4">
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
