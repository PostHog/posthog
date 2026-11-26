// PROTOTYPE, throwaway: variant D, a broadcast button in the cohort header, left of Save so Save keeps its place.
import { IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cohortBroadcastAudience, cohortBroadcastDisabledReason } from 'scenes/cohorts/cohortUtils'

import { CohortType } from '~/types'

import {
    captureMessageAudienceClicked,
    messageAudienceAccessDisabledReason,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { openMessageAudience } from 'products/workflows/frontend/MessageAudience/messageAudienceWarnings'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'

export function CohortHeaderMessageAction({ cohort }: { cohort: CohortType }): JSX.Element | null {
    const variant = useMessagingCtaVariant()

    if (variant !== 'D' || typeof cohort.id !== 'number') {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconLetter />}
            onClick={() => {
                captureMessageAudienceClicked(PROTOTYPE_SOURCES.cohortHeader, 'broadcast')
                void openMessageAudience(
                    { ...cohortBroadcastAudience(cohort), source: PROTOTYPE_SOURCES.cohortHeader },
                    'broadcast'
                )
            }}
            disabledReason={cohortBroadcastDisabledReason(cohort) ?? messageAudienceAccessDisabledReason()}
            tooltip="Send a one-time email to everyone in this cohort. Send yourself a test before it goes out."
            data-attr="cohort-header-message"
        >
            Email this cohort
        </LemonButton>
    )
}
