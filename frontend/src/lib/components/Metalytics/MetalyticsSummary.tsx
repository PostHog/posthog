import { IconPulse } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { metalyticsLogic } from './metalyticsLogic'

export function MetalyticsSummary(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading } = useValues(metalyticsLogic)
    const safeViewCount = viewCount ?? 0
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!instanceId || viewCountLoading) {
        return null
    }

    return (
        <IconWithCount count={safeViewCount}>
            <LemonButton
                loading={viewCountLoading}
                icon={<IconPulse />}
                size="small"
                onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
                tooltip="Click to see more usage data for this tool"
            />
        </IconWithCount>
    )
}
