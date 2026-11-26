// PROTOTYPE, throwaway: variant H, a row at the top of the recordings list about sessions that emails start.
import { IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'
import { openSendFromCodeSetup } from './sendFromCodePrototype'

export function ReplayListMessageRow(): JSX.Element | null {
    const variant = useMessagingCtaVariant()

    if (variant !== 'H') {
        return null
    }

    return (
        <div
            className="flex items-center justify-between gap-2 flex-wrap px-2 py-1.5 border-b bg-surface-primary"
            data-attr="replay-list-message-row"
        >
            <span className="flex items-center gap-1.5 text-xs text-secondary min-w-0">
                <IconLetter className="text-base shrink-0" />
                <span>See which emails start sessions</span>
            </span>
            <LemonButton
                type="secondary"
                size="xsmall"
                onClick={() => openSendFromCodeSetup(PROTOTYPE_SOURCES.replayList)}
                tooltip="Send your app's emails through PostHog. Sessions that start from an email link then show the email."
                data-attr="replay-list-message"
            >
                Send emails with PostHog
            </LemonButton>
        </div>
    )
}
