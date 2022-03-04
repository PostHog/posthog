import React from 'react'
import './PrimaryDashboardModal.scss'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { DashboardType } from '~/types'
import { Row, Skeleton } from 'antd'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import clsx from 'clsx'
import { HomeIcon } from 'lib/components/icons'

export interface ShareModalProps {
    visible: boolean
    onCancel: () => void
}

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
                <Skeleton active />
            ) : (
                <div className="dashboard-list">
                    {nameSortedDashboards.map((dashboard: DashboardType) => {
                        const isPrimary = dashboard.id === primaryDashboardId
                        return (
                            <Row
                                key={dashboard.id}
                                onClick={() => {
                                    if (!isPrimary) {
                                        setPrimaryDashboard(dashboard.id)
                                        closePrimaryDashboardModal()
                                    }
                                }}
                                className={clsx({
                                    'dashboard-row': true,
                                    'primary-dashboard-row': isPrimary,
                                })}
                            >
                                <div key={dashboard.id} className="dashboard-label-container">
                                    <strong>{dashboard.name}</strong>
                                    {dashboard.description && (
                                        <p className="text-small text-muted-alt dashboard-description">
                                            {dashboard.description}
                                        </p>
                                    )}
                                </div>
                                <div>
                                    {isPrimary ? (
                                        <div className="default-indicator">
                                            <HomeIcon className="mr-05" style={{ width: 18 }} />
                                            <span>Default</span>
                                        </div>
                                    ) : (
                                        <strong className="set-default-text">Set as default</strong>
                                    )}
                                </div>
                            </Row>
                        )
                    })}
                </div>
            )}
        </LemonModal>
    )
}
