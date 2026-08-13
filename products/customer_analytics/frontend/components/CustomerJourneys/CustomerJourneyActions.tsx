import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { CustomerJourneySelect } from './CustomerJourneySelect'
import { customerJourneysLogic } from './customerJourneysLogic'
import { DeleteJourneyButton } from './DeleteJourneyButton'

// Kept out of CustomerAnalyticsScene so customerJourneysLogic only mounts on the journeys tab.
// Reading its values in the scene mounted the logic on every tab, firing loadActiveInsight from
// the dashboard and surfacing a stray error toast when a journey pointed at a missing insight.
export function CustomerJourneyActions(): JSX.Element {
    const { activeJourney } = useValues(customerJourneysLogic)

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    return (
        <>
            <CustomerJourneySelect />
            <LemonButton
                type="primary"
                size="small"
                to={urls.customerJourneyTemplates()}
                data-attr="new-journey"
                disabledReason={accessControlDisabledReason}
            >
                New journey
            </LemonButton>
            {activeJourney && (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={`${urls.customerJourneyEdit(activeJourney.id)}?insightId=${activeJourney.insight}`}
                    data-attr="edit-journey"
                >
                    Edit
                </LemonButton>
            )}
            <DeleteJourneyButton />
        </>
    )
}
