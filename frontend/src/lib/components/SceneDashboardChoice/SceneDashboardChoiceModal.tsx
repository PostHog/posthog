import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sceneDashboardChoiceModalLogic, SceneDashboardChoiceModalProps } from './sceneDashboardChoiceModalLogic'
import { IconCottage } from 'lib/lemon-ui/icons'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonDivider, LemonInput } from '@posthog/lemon-ui'

export function SceneDashboardChoiceModal({ scene }: SceneDashboardChoiceModalProps): JSX.Element {
    const modalLogic = sceneDashboardChoiceModalLogic({ scene })
    const { isOpen, primaryDashboardId, dashboards, searchTerm } = useValues(modalLogic)
    const { closeSceneDashboardChoiceModal, setSceneDashboardChoice, setSearchTerm } = useActions(modalLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeSceneDashboardChoiceModal}
            title="Select a default dashboard for the project"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="close-primary-dashboard-modal"
                        onClick={closeSceneDashboardChoiceModal}
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
                        {dashboards.map((dashboard) => {
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
                                        setSceneDashboardChoice(dashboard.id)
                                        setSearchTerm('')
                                        closeSceneDashboardChoiceModal()
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
