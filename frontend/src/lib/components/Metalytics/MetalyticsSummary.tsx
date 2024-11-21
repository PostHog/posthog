import { IconEye } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { metalyticsLogic } from './metalyticsLogic'

export function MetalyticsSummary(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading } = useValues(metalyticsLogic)

    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!instanceId) {
        return null
    }

    return (
        <LemonButton
            loading={viewCountLoading}
            type="secondary"
            icon={<IconEye />}
            size="small"
            onClick={() => openSidePanel(SidePanelTab.Activity, 'metalytics')}
        >
            {viewCount === null ? 'Loading...' : `Viewed ${viewCount} times`}
        </LemonButton>
    )
}
