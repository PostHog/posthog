import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { customerJourneysLogic } from './customerJourneysLogic'
import { openDeleteJourneyDialog } from './openDeleteJourneyDialog'

export function QuillDeleteJourneyButton(): JSX.Element | null {
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
        <Button
            variant="destructive-outline"
            disabledReason={accessControlDisabledReason}
            onClick={() =>
                openDeleteJourneyDialog({
                    journeyId: activeJourney.id,
                    deleteJourney,
                    reportCustomerJourneyDeleted,
                })
            }
            tooltip="Delete this journey"
        >
            Delete journey
        </Button>
    )
}
