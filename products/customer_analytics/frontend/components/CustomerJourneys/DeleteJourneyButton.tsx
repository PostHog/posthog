import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { customerJourneysLogic } from './customerJourneysLogic'
import { openDeleteJourneyDialog } from './openDeleteJourneyDialog'
import { QuillDeleteJourneyButton } from './QuillDeleteJourneyButton'

export function DeleteJourneyButton(): JSX.Element | null {
    const { activeJourney } = useValues(customerJourneysLogic)
    const { deleteJourney } = useActions(customerJourneysLogic)
    const { reportCustomerJourneyDeleted } = useActions(eventUsageLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillDeleteJourneyButton />
    }

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
                openDeleteJourneyDialog({
                    journeyId: activeJourney.id,
                    deleteJourney,
                    reportCustomerJourneyDeleted,
                })
            }
            tooltip="Delete this journey"
            children="Delete journey"
        />
    )
}
