// PROTOTYPE, throwaway: variant E, a row under "Flag targeting" that automates an email to people as they join.
import { router } from 'kea-router'

import { IconInfo, IconSend } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { hasEventCriteria } from 'scenes/cohorts/cohortUtils'

import { CohortType } from '~/types'

import {
    captureMessageAudienceClicked,
    messageAudienceAccessDisabledReason,
    messageAudienceUrl,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { cohortMembershipEventEntry } from 'products/workflows/frontend/Workflows/hogflows/steps/components/cohortMembershipEvent'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'

export function CohortRealtimeMessageAction({ cohort }: { cohort: CohortType }): JSX.Element | null {
    const variant = useMessagingCtaVariant()

    if (variant !== 'E' || typeof cohort.id !== 'number' || !hasEventCriteria(cohort)) {
        return null
    }
    const cohortId = cohort.id

    return (
        <div className="flex items-center gap-x-2 my-0 flex-wrap" data-attr="cohort-realtime-message-row">
            <strong>When people join:</strong>
            <Tooltip title="Real-time cohorts know the moment someone joins. A workflow can send them an email right then.">
                <IconInfo className="text-secondary text-base" />
            </Tooltip>
            <span className="text-secondary">No email yet</span>
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconSend />}
                onClick={() => {
                    captureMessageAudienceClicked(PROTOTYPE_SOURCES.cohortRealtime, 'workflow')
                    router.actions.push(
                        messageAudienceUrl(
                            {
                                source: PROTOTYPE_SOURCES.cohortRealtime,
                                sourceRecord: `cohort:${cohortId}`,
                                properties: [],
                                workflowTrigger: {
                                    type: 'event',
                                    filters: cohortMembershipEventEntry({ cohortId, transition: 'entered' }).filters,
                                },
                            },
                            'workflow'
                        )
                    )
                }}
                disabledReason={messageAudienceAccessDisabledReason()}
                tooltip="Opens a workflow that starts when someone joins this cohort. Nothing sends until you turn it on."
                data-attr="cohort-realtime-message"
            >
                Email people as they join
            </LemonButton>
        </div>
    )
}
