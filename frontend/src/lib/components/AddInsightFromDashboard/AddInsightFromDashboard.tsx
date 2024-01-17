import { LemonButton } from '@posthog/lemon-ui'

import { DashboardType } from '~/types'

interface AddInsightFromDashboardProps {
    setAddInsightFromDashboardModalOpen: (open: boolean) => void
    dashboard: DashboardType
    disabledReason: string | null
}

export function AddInsightFromDashboard({
    setAddInsightFromDashboardModalOpen,
    dashboard,
    disabledReason,
}: AddInsightFromDashboardProps): JSX.Element | null {
    return (
        <LemonButton
            onClick={() => {
                setAddInsightFromDashboardModalOpen(true)
            }}
            type="primary"
            data-attr="dashboard-add-graph"
            disabledReason={disabledReason}
        >
            {dashboard.tiles.every((tile) => !tile.insight) ? 'Add Insight' : 'Manage Insights'}
        </LemonButton>
    )
}
