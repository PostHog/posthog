import { IconPulse } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { FlaggedFeature } from '../FlaggedFeature'
import { metalyticsLogic } from '../Metalytics/metalyticsLogic'

export function SceneMetalyticsSummaryButton(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading } = useValues(metalyticsLogic)
    const safeViewCount = viewCount?.views ?? 0
    const safeUniqueUsers = viewCount?.users ?? 0
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!instanceId) {
        return null
    }

    return (
        <FlaggedFeature flag="metalytics">
            <ButtonPrimitive
                onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
                tooltip={`${safeUniqueUsers} PostHog members have viewed this a total of ${safeViewCount} times. Click to see more.`}
                menuItem
                disabled={viewCountLoading}
            >
                {viewCountLoading ? <Spinner textColored /> : <IconPulse />}
                Metalytics
            </ButtonPrimitive>
        </FlaggedFeature>
    )
}
