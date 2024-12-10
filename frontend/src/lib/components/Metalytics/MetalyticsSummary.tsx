import { IconPulse } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { metalyticsLogic } from './metalyticsLogic'

export function MetalyticsSummary(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading } = useValues(metalyticsLogic)
    const safeViewCount = viewCount?.views ?? 0
    const safeUniqueUsers = viewCount?.users ?? 0
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!instanceId || viewCountLoading) {
        return null
    }

    return (
        <span className="relative inline-flex">
            <LemonButton
                loading={viewCountLoading}
                icon={<IconPulse />}
                size="small"
                onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
                tooltip={`${safeUniqueUsers} PostHog members have viewed this a total of ${safeViewCount} times. Click to see more.`}
            />
            <LemonBadge.Number
                count={safeViewCount}
                size="small"
                position="top-right"
                showZero={false}
                status="primary"
                maxDigits={3}
            />
        </span>
    )
}
