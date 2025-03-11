import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { dashboardInsightColorsLogic } from './dashboardInsightColorsLogic'

export function DashboardInsightColorsModal(): JSX.Element {
    const { dashboardInsightColorsModalVisible, insightTiles } = useValues(dashboardInsightColorsLogic)
    const { hideDashboardInsightColorsModal } = useActions(dashboardInsightColorsLogic)

    return (
        <LemonModal
            title="Insight Colors"
            isOpen={dashboardInsightColorsModalVisible}
            onClose={hideDashboardInsightColorsModal}
        >
            <span>DashboardInsightColorsModal</span>
            <pre>{JSON.stringify(insightTiles, null, 2)}</pre>
        </LemonModal>
    )
}
