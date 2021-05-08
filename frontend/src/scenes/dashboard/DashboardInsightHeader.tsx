import React, { useState } from 'react'
import { Link } from 'lib/components/Link'
import { PageHeader } from 'lib/components/PageHeader'
import { ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import { IconDashboard } from 'lib/components/icons'
import { useActions, useValues } from 'kea'
import { dashboardLogic } from './dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { Button, Card, Input } from 'antd'
import { DashboardItemMode } from '../../types'
import './DashboardInsight.scss'

interface Props {
    dashboardId: number
}

export function DashboardInsightHeader({ dashboardId }: Props): JSX.Element {
    const { dashboard } = useValues(dashboardLogic({ id: dashboardId }))
    const { dashboardItem } = useValues(insightLogic)
    const { dashboardItemMode } = useValues(dashboardItemsModel)
    const { setDashboardItemMode, updateDashboardItem } = useActions(dashboardItemsModel)
    const [newDescription, setNewDescription] = useState(dashboardItem.description) // Used to update the input immediately, debouncing API calls
    const { user } = useValues(userLogic)
    const isDashboardItemEditMode = dashboardItemMode === DashboardItemMode.Edit
    const hasDashboardCollab = user?.organization?.available_features?.includes('dashboard_collaboration')

    return (
        <div className="dashboard-insight-header">
            <Link to={`/dashboard/${dashboardId}`}>
                <ArrowLeftOutlined /> To {dashboard?.name} dashboard
            </Link>

            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardItem?.name} />

                <div className="header-container text-default">
                    <div className="title-description">
                        <div className="status" style={{ display: 'flex' }}>
                            <div className="status-svg">
                                {isDashboardItemEditMode ? <EditOutlined /> : <IconDashboard />}
                            </div>
                            <span style={{ paddingLeft: 6 }}>
                                {isDashboardItemEditMode ? 'Editing graph' : 'Viewing graph'}{' '}
                                <b>{dashboardItem?.name}</b> from{' '}
                                <Link to={`/dashboard/${dashboardId}`}>{dashboard?.name}</Link> dashboard.
                            </span>
                        </div>

                        {hasDashboardCollab && (
                            <Card className="dashboard-insight-description" bordered={false}>
                                {isDashboardItemEditMode ? (
                                    <div className="edit-box">
                                        <Input.TextArea
                                            placeholder="Add a description to your dashboard insight that helps others understand it better."
                                            value={newDescription}
                                            onChange={(e) => {
                                                setNewDescription(e.target.value)
                                            }}
                                            autoSize
                                            allowClear
                                        />
                                    </div>
                                ) : (
                                    <div
                                        className="description-box"
                                        onClick={() => setDashboardItemMode(DashboardItemMode.Edit)}
                                    >
                                        {dashboardItem.description ? (
                                            <span>{dashboardItem.description}</span>
                                        ) : (
                                            <span className="text-muted">
                                                Add a description for this dashboard insight...
                                            </span>
                                        )}
                                        <EditOutlined />
                                    </div>
                                )}
                            </Card>
                        )}
                    </div>
                    {hasDashboardCollab && isDashboardItemEditMode && (
                        <Button
                            style={{ marginLeft: 8, alignSelf: 'flex-end' }}
                            onClick={() =>
                                newDescription !== dashboardItem.description
                                    ? updateDashboardItem(dashboardItem.id, { description: newDescription })
                                    : setDashboardItemMode(null)
                            }
                            type="primary"
                            data-attr="dashboard-insight-description-submit"
                        >
                            Finish
                        </Button>
                    )}
                </div>
            </div>
        </div>
    )
}
