import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'

import { dashboardInsightColorsLogic } from './dashboardInsightColorsLogic'

export function DashboardInsightColorsModal(): JSX.Element {
    const { dashboardInsightColorsModalVisible, insightTiles, insightTilesLoading } =
        useValues(dashboardInsightColorsLogic)
    const { hideDashboardInsightColorsModal } = useActions(dashboardInsightColorsLogic)

    return (
        <LemonModal
            title="Insight Colors"
            isOpen={dashboardInsightColorsModalVisible}
            onClose={hideDashboardInsightColorsModal}
        >
            {insightTilesLoading ? (
                <div className="flex flex-col items-center">
                    {/* Slightly offset to the left for visual balance. */}
                    <Animation type={AnimationType.SportsHog} size="large" className="-ml-4" />
                    <p className="text-primary">Waiting for dashboard tiles to load and refresh…</p>
                </div>
            ) : (
                <>
                    <span>DashboardInsightColorsModal</span>
                    <pre>{JSON.stringify(insightTiles, null, 2)}</pre>
                </>
            )}
        </LemonModal>
    )
}
