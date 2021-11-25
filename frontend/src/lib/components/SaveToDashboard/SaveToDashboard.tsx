import React, { useState } from 'react'
import { Button } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { DashboardItemType } from '~/types'
import { CheckSquareOutlined } from '@ant-design/icons'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useValues } from 'kea'
import { LinkButton } from '../LinkButton'
import { urls } from '../../../scenes/urls'
import { Tooltip } from '../Tooltip'
import { combineUrl } from 'kea-router'

interface Props {
    insight: Partial<DashboardItemType>
}

export function SaveToDashboard({ insight }: Props): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboard = (insight.dashboard && rawDashboards[insight.dashboard]) || null

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            <SaveToDashboardModal visible={openModal} closeModal={() => setOpenModal(false)} insight={insight} />
            {dashboard ? (
                <Tooltip title={`Go to dashboard "${dashboard?.name}"`} placement="bottom">
                    <LinkButton
                        to={combineUrl(urls.dashboard(dashboard.id), { highlightInsightId: insight.short_id }).url}
                        type="default"
                        style={{ color: 'var(--primary)' }}
                        icon={<CheckSquareOutlined />}
                        className="btn-save"
                    >
                        On dashboard
                    </LinkButton>
                </Tooltip>
            ) : (
                <Button
                    onClick={() => setOpenModal(true)}
                    type="default"
                    style={{ color: 'var(--primary)' }}
                    className="btn-save"
                >
                    Add to dashboard
                </Button>
            )}
        </span>
    )
}
