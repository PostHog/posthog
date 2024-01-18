import { LemonButton } from '@posthog/lemon-ui'

import { DashboardType } from '~/types'

interface AddInsightsToDashboardProps {
    setAddInsightsToDashboardModalOpen: (open: boolean) => void
    dashboard: DashboardType
    disabledReason: string | null
}

export function AddInsightsToDashboard({
    setAddInsightsToDashboardModalOpen,
    dashboard,
    disabledReason,
}: AddInsightsToDashboardProps): JSX.Element | null {
    return (
        <LemonButton
            onClick={() => {
                setAddInsightsToDashboardModalOpen(true)
            }}
            type="primary"
            data-attr="insight-add-graph"
            disabledReason={disabledReason}
        >
            {dashboard.tiles.every((tile) => !tile.insight) ? 'Add Insight' : 'Manage Insights'}
        </LemonButton>
    )
}
