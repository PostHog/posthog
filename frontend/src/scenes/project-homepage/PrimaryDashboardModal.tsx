import React from 'react'
import './PrimaryDashboardModal.scss'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonButton } from 'lib/components/LemonButton'
import { DashboardType } from '~/types'
import { Skeleton } from 'antd'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { IconCottage } from 'lib/components/icons'
import { LemonRow } from 'lib/components/LemonRow'
import { LemonModalV2 } from 'lib/components/LemonModalV2'

export function PrimaryDashboardModal(): JSX.Element {
    const { visible, primaryDashboardId } = useValues(primaryDashboardModalLogic)
    const { closePrimaryDashboardModal, setPrimaryDashboard } = useActions(primaryDashboardModalLogic)
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)

    return (
        <LemonModalV2
            isOpen={visible}
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
                <div className="p-4">
                    <Skeleton active />
                </div>
            ) : (
                <div className="space-y-2">
                    {nameSortedDashboards.map((dashboard: DashboardType) => {
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
            )}
        </LemonModalV2>
    )
}
