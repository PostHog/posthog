import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { customerJourneysLogic } from './customerJourneysLogic'

export function DeleteJourneyButton(): JSX.Element | null {
    const { activeJourney } = useValues(customerJourneysLogic)
    const { deleteJourney } = useActions(customerJourneysLogic)
    const { reportCustomerJourneyDeleted } = useActions(eventUsageLogic)

    if (!activeJourney) {
        return null
    }

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    return (
        <LemonButton
            size="small"
            type="secondary"
            status="danger"
            disabledReason={accessControlDisabledReason}
            onClick={() =>
                LemonDialog.open({
                    title: 'Delete customer journey',
                    content: 'Are you sure you want to delete this journey? This action cannot be undone.',
                    primaryButton: {
                        children: 'Delete',
                        onClick: () => {
                            reportCustomerJourneyDeleted(activeJourney.id)
                            deleteJourney(activeJourney.id)
                        },
                        status: 'danger',
                    },
                    secondaryButton: {
                        children: 'Cancel',
                    },
                })
            }
            tooltip="Delete this journey"
            children="Delete journey"
        />
    )
}
