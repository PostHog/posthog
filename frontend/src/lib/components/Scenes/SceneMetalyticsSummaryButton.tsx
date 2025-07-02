import { IconPulse } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { metalyticsLogic } from '../Metalytics/metalyticsLogic'
import { FlaggedFeature } from '../FlaggedFeature'

export function SceneMetalyticsSummaryButton(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading } = useValues(metalyticsLogic)
    const safeViewCount = viewCount?.views ?? 0
    const safeUniqueUsers = viewCount?.users ?? 0
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!instanceId || viewCountLoading) {
        return null
    }

    return (
        <FlaggedFeature flag="metalytics">
            <LemonButton
                loading={viewCountLoading}
                icon={<IconPulse />}
                size="small"
                onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
                tooltip={`${safeUniqueUsers} PostHog members have viewed this a total of ${safeViewCount} times. Click to see more.`}
            >
                Metalytics
            </LemonButton>
        </FlaggedFeature>
    )
}
