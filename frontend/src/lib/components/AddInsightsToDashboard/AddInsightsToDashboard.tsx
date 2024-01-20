import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

interface AddInsightsToDashboardProps {
    dashboardId: number
    setAddInsightsToDashboardModalOpen: (open: boolean) => void
    disabledReason: string | null
}

export function AddInsightsToDashboard({
    dashboardId,
    setAddInsightsToDashboardModalOpen,
    disabledReason,
}: AddInsightsToDashboardProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <LemonButton
            onClick={() => {
                setAddInsightsToDashboardModalOpen(true)
            }}
            type="primary"
            data-attr="insight-add-graph"
            disabledReason={disabledReason}
            sideAction={{
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <>
                            <LemonButton
                                fullWidth
                                onClick={() => push(urls.dashboardTextTile(dashboardId, 'new'))}
                                data-attr="add-text-tile-to-dashboard"
                            >
                                Add text card
                            </LemonButton>
                        </>
                    ),
                },
                disabled: false,
                'data-attr': 'dashboard-add-dropdown',
            }}
        >
            Add insight
        </LemonButton>
    )
}
