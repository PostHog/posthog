import React, { useState } from 'react'
import { Button, Tooltip } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { DashboardItemType } from '~/types'
import { CheckSquareOutlined } from '@ant-design/icons'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useValues } from 'kea'

interface Props {
    insight: Partial<DashboardItemType>
}

export function SaveToDashboard({ insight }: Props): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboard = (insight.dashboard && rawDashboards[insight.dashboard]) || null

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            {openModal && <SaveToDashboardModal closeModal={() => setOpenModal(false)} insight={insight} />}
            <Tooltip title={dashboard?.name ? `Saved on "${dashboard?.name}"` : undefined}>
                <Button
                    onClick={() => setOpenModal(true)}
                    type="default"
                    style={{ color: 'var(--primary)' }}
                    icon={!!insight.dashboard ? <CheckSquareOutlined /> : null}
                    className="btn-save"
                >
                    {!!insight.dashboard ? 'On dashboard' : 'Add to dashboard'}
                </Button>
            </Tooltip>
        </span>
    )
}
