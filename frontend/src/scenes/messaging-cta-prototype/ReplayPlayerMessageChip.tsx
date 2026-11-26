// PROTOTYPE, throwaway: variant G, a chip in the player bar that asks which email started the session.
import { IconLetter } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'
import { openSendFromCodeSetup } from './sendFromCodePrototype'

export function ReplayPlayerMessageChip(): JSX.Element | null {
    const variant = useMessagingCtaVariant()
    const canOpenSetup = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')

    if (variant !== 'G' || !canOpenSetup) {
        return null
    }

    return (
        <Tooltip title="Send your app's emails through PostHog to see which email started each session.">
            <LemonTag
                type="option"
                icon={<IconLetter />}
                onClick={() => openSendFromCodeSetup(PROTOTYPE_SOURCES.replayPlayer)}
                className="shrink-0 cursor-pointer"
                data-attr="replay-player-message-chip"
            >
                From an email?
            </LemonTag>
        </Tooltip>
    )
}
