import { Button, Card, Input, PageHeader } from "antd"
import { useValues, useActions } from "kea"
import { IconDashboard } from "lib/components/icons"
import { Link } from "lib/components/Link"
import React, { useState } from "react"
import { userLogic } from "scenes/userLogic"
import { dashboardItemsModel } from "~/models/dashboardItemsModel"
import { DashboardItemType } from "~/types"
import { ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import './DashboardInsight.scss'

interface Props {
    dashboardInsight: DashboardItemType,
    dashboardName: string
}

export function DashboardInsightHeader({ dashboardInsight, dashboardName }: Props): JSX.Element {
    // const { dashboardItemMode } = useValues(dashboardItemsModel)
    // const { setDashboardItemMode, updateDashboardItem } = useActions(dashboardItemsModel)
    const [newDescription, setNewDescription] = useState(dashboardInsight.description) // Used to update the input immediately, debouncing API calls
    const { user } = useValues(userLogic)
    const isDashboardCollab = user?.organization?.available_features?.includes('dashboard_collaboration')
    // const isDashboardItemEditMode = dashboardItemMode === DashboardItemMode.Edit
    const isDashboardItemEditMode = true

    return (
        <div className="dashboard-insight-header">
            <Link to={`/dashboard/${dashboardInsight.dashboard}`}>
                <ArrowLeftOutlined /> To {dashboardName} dashboard
            </Link>

            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardInsight.name} />

                <div className="header-container text-default">
                    <div className="title-description">
                        <div className="status" style={{ display: 'flex' }}>
                            <div className="status-svg">
                                {isDashboardItemEditMode ? <EditOutlined /> : <IconDashboard />}
                            </div>
                            <span style={{ paddingLeft: 6 }}>
                                {isDashboardItemEditMode ? 'Editing graph' : 'Viewing graph'}{' '}
                                <b>{dashboardInsight.name}</b> from{' '}
                                <Link to={`/dashboard/${dashboardInsight.dashboard}`}>{dashboardName}</Link> dashboard.
                            </span>
                        </div>

                        {isDashboardCollab && (
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
                                        // onClick={() => setDashboardItemMode(DashboardItemMode.Edit)}
                                    >
                                        {dashboardInsight.description ? (
                                            <span>{dashboardInsight.description}</span>
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
                    {/* {isDashboardCollab && isDashboardItemEditMode && (
                        <Button
                            style={{ marginLeft: 8, alignSelf: 'flex-end' }}
                            onClick={() =>
                                newDescription !== dashboardInsight.description
                                    ? updateDashboardItem(dashboardInsight.id, { description: newDescription })
                                    : setDashboardItemMode(null)
                            }
                            type="primary"
                            data-attr="dashboard-insight-description-submit"
                        >
                            Finish
                        </Button>
                    )} */}
                </div>
            </div>
        </div>
    )
}