// PROTOTYPE, throwaway: variant C, an announcement row in the status card once a flag is on for everyone.
import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from 'scenes/messaging-cta-prototype/messagingCtaPrototype'

import {
    FINDING_FLAG_PEOPLE_MESSAGE,
    broadcastNoOneReason,
    featureFlagLogic,
    isOnForEveryone,
} from '../featureFlagLogic'

export function EveryoneMessageAction(): JSX.Element | null {
    const variant = useMessagingCtaVariant()
    const { featureFlag, broadcastCohortLoading } = useValues(featureFlagLogic)
    const { findOrCreateBroadcastCohort } = useActions(featureFlagLogic)

    if (variant !== 'C' || !isOnForEveryone(featureFlag)) {
        return null
    }

    return (
        <div className="flex items-center justify-between gap-2 flex-wrap border-t pt-3">
            <div className="flex flex-col">
                <span className="text-sm font-medium">On for everyone</span>
                <span className="text-xs text-secondary">Let the people who have it know it's here.</span>
            </div>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconSend />}
                onClick={() => findOrCreateBroadcastCohort(PROTOTYPE_SOURCES.everyone)}
                loading={broadcastCohortLoading}
                disabledReason={
                    broadcastCohortLoading ? FINDING_FLAG_PEOPLE_MESSAGE : broadcastNoOneReason(featureFlag)
                }
                tooltip="Opens a broadcast to the people this flag is on for now. Send yourself a test before it goes out."
                data-attr="feature-flag-everyone-message"
            >
                Announce it
            </LemonButton>
        </div>
    )
}
