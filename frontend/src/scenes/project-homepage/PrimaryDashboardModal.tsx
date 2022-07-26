import React from 'react'
import './PrimaryDashboardModal.scss'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { DashboardType } from '~/types'
import { Skeleton, Typography } from 'antd'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { IconCottage } from 'lib/components/icons'
import { LemonRow } from 'lib/components/LemonRow'

export function PrimaryDashboardModal(): JSX.Element {
    const { visible, primaryDashboardId } = useValues(primaryDashboardModalLogic)
    const { closePrimaryDashboardModal, setPrimaryDashboard } = useActions(primaryDashboardModalLogic)
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)

    return (
        <LemonModal
            className="primary-dashboard-modal"
            visible={visible}
            onCancel={() => {
                closePrimaryDashboardModal()
            }}
            title="Select a default dashboard for the project"
            destroyOnClose
            bodyStyle={{ padding: 0 }}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="close-primary-dashboard-modal"
                        style={{ marginRight: '0.5rem' }}
                        onClick={closePrimaryDashboardModal}
                    >
                        Close
                    </LemonButton>
                </>
            }
        >
            {dashboardsLoading ? (
                <div className="loading-skeleton-container">
                    <Skeleton active />
                </div>
            ) : (
                <div className="dashboard-list">
                    {nameSortedDashboards.map((dashboard: DashboardType) => {
                        const isPrimary = dashboard.id === primaryDashboardId
                        const rowContents = (
                            <>
                                <div className="dashboard-label-container">
                                    <strong>{dashboard.name}</strong>
                                    <Typography.Paragraph
                                        ellipsis={{ rows: 1 }}
                                        className="text-small dashboard-description"
                                    >
                                        {dashboard.description}
                                    </Typography.Paragraph>
                                </div>
                                {isPrimary ? (
                                    <div className="default-indicator">
                                        <IconCottage className="mr-2 text-warning" style={{ fontSize: '1.5rem' }} />
                                        <span>Default</span>
                                    </div>
                                ) : (
                                    <strong className="set-default-text">Set as default</strong>
                                )}
                            </>
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
        </LemonModal>
    )
}
