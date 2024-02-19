import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { urls } from 'scenes/urls'

interface AddInsightsToDashboardProps {
    disabledReason: string | null
}

export function AddInsightsToDashboard({ disabledReason }: AddInsightsToDashboardProps): JSX.Element {
    const { push } = useActions(router)
    const { addInsightsModalOpen } = useActions(dashboardLogic)
    const { dashboard } = useValues(dashboardLogic)

    return (
        <>
            {dashboard && (
                <LemonButton
                    onClick={() => addInsightsModalOpen(true)}
                    type="primary"
                    data-attr="dashboard-add-graph-header"
                    disabledReason={disabledReason}
                    sideAction={{
                        dropdown: {
                            placement: 'bottom-end',
                            overlay: (
                                <LemonButton
                                    fullWidth
                                    onClick={() => push(urls.dashboardTextTile(dashboard.id, 'new'))}
                                    data-attr="add-text-tile-to-dashboard"
                                >
                                    Add text card
                                </LemonButton>
                            ),
                        },
                        disabled: false,
                        'data-attr': 'dashboard-add-dropdown',
                    }}
                >
                    Add insight
                </LemonButton>
            )}
        </>
    )
}
