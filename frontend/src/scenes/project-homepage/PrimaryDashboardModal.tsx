import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonTable } from 'lib/components/LemonTable'
import { DashboardType } from '~/types'
import { Skeleton, Typography } from 'antd'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'

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
                <LemonTable
                    embedded
                    showHeader={false}
                    rowKey="id"
                    columns={[
                        {
                            key: 'dashboard',
                            render: function Render(_, dashboard: DashboardType) {
                                return (
                                    <div key={dashboard.id}>
                                        <strong>{dashboard.name}</strong>
                                        <p className="text-small text-muted-alt">{dashboard.description}</p>
                                    </div>
                                )
                            },
                        },
                        {
                            width: 0,
                            key: 'setDefault',
                            render: function Render(_, dashboard: DashboardType) {
                                if (dashboard.id === primaryDashboardId) {
                                    return <Typography.Text>Default</Typography.Text>
                                }
                                return (
                                    <LemonButton
                                        type="default"
                                        fullWidth
                                        onClick={() => {
                                            setPrimaryDashboard(dashboard.id)
                                            closePrimaryDashboardModal()
                                        }}
                                    >
                                        Set as default
                                    </LemonButton>
                                )
                            },
                        },
                    ]}
                    dataSource={nameSortedDashboards}
                />
            )}
        </LemonModal>
    )
}
