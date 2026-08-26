import { useActions, useValues } from 'kea'

import { phaiLegacyNudgeLogic } from '../logics/phaiLegacyNudgeLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { PhaiLegacyNudgeBanner } from './PhaiLegacyNudgeBanner'

export interface MaybePhaiLegacyNudgeProps {
    /** Identifies the host panel, so the `/ai` scene and the side panel keep separate questions. */
    panelId: string
}

/**
 * Decides whether to offer a user who switched back to the legacy chat a route into the new PostHog AI. Reads
 * the thread through the host's `BindLogic`, the same arrangement `MaxWebAnalyticsNudge` uses.
 *
 * Temporary migration affordance - delete alongside `scenes/max` once everyone is on the new PostHog AI.
 */
export function MaybePhaiLegacyNudge({ panelId }: MaybePhaiLegacyNudgeProps): JSX.Element | null {
    const { threadGrouped, streamingActive, isSharedThread } = useValues(maxThreadLogic)
    const { conversationId } = useValues(maxLogic)

    const logic = phaiLegacyNudgeLogic({ panelId, threadGrouped, streamingActive, isSharedThread, conversationId })
    const { shouldShow, reasonPromptVisible, lastHumanQuestion, otherReasonSelected, otherReasonText } =
        useValues(logic)
    const {
        nudgeClicked,
        nudgeDismissed,
        submitReason,
        closeReasonPrompt,
        selectOtherReason,
        setOtherReasonText,
        submitOtherReason,
    } = useActions(logic)

    if (!shouldShow && !reasonPromptVisible) {
        return null
    }

    return (
        <PhaiLegacyNudgeBanner
            mode={reasonPromptVisible ? 'reason' : 'offer'}
            hasQuestion={!!lastHumanQuestion}
            otherReasonSelected={otherReasonSelected}
            otherReasonText={otherReasonText}
            onAccept={nudgeClicked}
            onDismiss={reasonPromptVisible ? closeReasonPrompt : nudgeDismissed}
            onSubmitReason={submitReason}
            onSelectOtherReason={selectOtherReason}
            onChangeOtherReasonText={setOtherReasonText}
            onSubmitOtherReason={submitOtherReason}
        />
    )
}
