// PROTOTYPE, throwaway: variant B, a broadcast action on the rollout line of a partly rolled out condition set.
import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FINDING_FLAG_PEOPLE_MESSAGE, broadcastNoOneReason, featureFlagLogic } from '../featureFlagLogic'
import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'

export function PartialRolloutMessageAction({ rollout }: { rollout: number }): JSX.Element | null {
    const variant = useMessagingCtaVariant()
    const { featureFlag, broadcastCohortLoading } = useValues(featureFlagLogic)
    const { findOrCreateBroadcastCohort } = useActions(featureFlagLogic)

    if (variant !== 'B' || !featureFlag.active || rollout <= 0 || rollout >= 100) {
        return null
    }

    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconSend />}
            onClick={() => findOrCreateBroadcastCohort(PROTOTYPE_SOURCES.partialRollout)}
            loading={broadcastCohortLoading}
            disabledReason={broadcastCohortLoading ? FINDING_FLAG_PEOPLE_MESSAGE : broadcastNoOneReason(featureFlag)}
            tooltip="Opens a broadcast to the people this flag is on for now. Send yourself a test before it goes out."
            data-attr="feature-flag-partial-rollout-message"
        >
            Email the people who have it
        </LemonButton>
    )
}
