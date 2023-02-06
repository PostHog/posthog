import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardType } from '~/types'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { IconCottage } from 'lib/lemon-ui/icons'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonDivider, LemonInput } from '@posthog/lemon-ui'

export function PrimaryDashboardModal(): JSX.Element {
    const { isOpen, primaryDashboardId, dashboards, searchTerm } = useValues(primaryDashboardModalLogic)
    const { closePrimaryDashboardModal, setPrimaryDashboard, setSearchTerm } = useActions(primaryDashboardModalLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closePrimaryDashboardModal}
            title="Select a default dashboard for the project"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="close-primary-dashboard-modal"
                        onClick={closePrimaryDashboardModal}
                    >
                        Close
                    </LemonButton>
                </>
            }
        >
            {dashboardsLoading ? (
                <div className="space-y-2">
                    <LemonSkeleton.Row repeat={4} />
                </div>
            ) : (
                <>
                    <LemonInput
                        type="search"
                        placeholder="Search for dashboards"
                        onChange={setSearchTerm}
                        value={searchTerm}
                        fullWidth={true}
                        allowClear={true}
                        className="mb-4"
                    />
                    <LemonDivider />
                    <div className="space-y-2 min-h-100">
                        {dashboards.map((dashboard: DashboardType) => {
                            const isPrimary = dashboard.id === primaryDashboardId
                            const rowContents = (
                                <div className="flex flex-1 items-center justify-between overflow-hidden">
                                    <div className="flex-1 flex flex-col justify-center overflow-hidden">
                                        <strong>{dashboard.name}</strong>
                                        <span className="text-default font-normal text-ellipsis">
                                            {dashboard.description}
                                        </span>
                                    </div>
                                    {isPrimary ? (
                                        <>
                                            <IconCottage className="mr-2 text-warning text-lg" />
                                            <span>Default</span>
                                        </>
                                    ) : (
                                        <strong className="set-default-text">Set as default</strong>
                                    )}
                                </div>
                            )
                            if (isPrimary) {
                                return (
                                    <LemonRow key={dashboard.id} fullWidth status="muted" className="dashboard-row">
                                        {rowContents}
                                    </LemonRow>
                                )
                            }
                            return (
                                <LemonButton
                                    key={dashboard.id}
                                    fullWidth
                                    className="dashboard-row"
                                    onClick={() => {
                                        setPrimaryDashboard(dashboard.id)
                                        closePrimaryDashboardModal()
                                    }}
                                >
                                    {rowContents}
                                </LemonButton>
                            )
                        })}
                    </div>
                </>
            )}
        </LemonModal>
    )
}
