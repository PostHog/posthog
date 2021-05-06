import React, { useState } from 'react'
import { Link } from 'lib/components/Link'
import { PageHeader } from 'lib/components/PageHeader'
import { ArrowLeftOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons'
import { IconDashboard } from 'lib/components/icons'
import { useActions, useValues } from 'kea'
import { dashboardLogic } from './dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { Button, Input } from 'antd'
import { DashboardItemMode } from '../../types'
import './DashboardItem.scss'

interface Props {
    dashboardId: number
}

export function DashboardItemHeader({ dashboardId }: Props): JSX.Element {
    const { dashboard } = useValues(dashboardLogic({ id: dashboardId }))
    const { dashboardItem } = useValues(insightLogic)
    const { dashboardItemMode } = useValues(dashboardItemsModel)
    const { setDashboardItemMode, updateDashboardItem } = useActions(dashboardItemsModel)
    const [newDescription, setNewDescription] = useState(dashboardItem.description) // Used to update the input immediately, debouncing API calls
    const { user } = useValues(userLogic)
    const isDashboardItemEditMode = dashboardItemMode === DashboardItemMode.Edit
    const hasDashboardCollab = user?.organization?.available_features?.includes('dashboard_collaboration')

    return (
        <div className="dashboard-item-header">
            <Link to={`/dashboard/${dashboardId}`}>
                <ArrowLeftOutlined /> To {dashboard?.name} dashboard
            </Link>

            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardItem?.name} />

                <div className="header-container text-default">
                    <div className="title-description">
                        <div style={{ display: 'flex' }}>
                            {isDashboardItemEditMode ? <EditOutlined /> : <IconDashboard />}
                            <span style={{ paddingLeft: 6 }}>
                                {isDashboardItemEditMode ? 'Editing graph' : 'Viewing graph'}{' '}
                                <b>{dashboardItem?.name}</b> from{' '}
                                <Link to={`/dashboard/${dashboardId}`}>{dashboard?.name}</Link> dashboard.
                            </span>
                        </div>

                        {hasDashboardCollab && (
                            <>
                                <div className="description">
                                    {isDashboardItemEditMode ? (
                                        <div className="edit-box">
                                            <Input.TextArea
                                                placeholder="Add a description to your dashboard item"
                                                value={newDescription}
                                                onChange={(e) => {
                                                    setNewDescription(e.target.value)
                                                }}
                                            />
                                        </div>
                                    ) : (
                                        <div className="description-box text-small text-muted">
                                            {dashboardItem.description ? (
                                                <span>{dashboardItem.description}</span>
                                            ) : (
                                                <span className="add-description">Add a description...</span>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </>
                        )}
                    </div>

                    {hasDashboardCollab &&
                        (isDashboardItemEditMode ? (
                            <Button
                                style={{ marginRight: 16 }}
                                icon={<SaveOutlined />}
                                onClick={() => updateDashboardItem(dashboardItem.id, { description: newDescription })}
                                type="primary"
                                data-attr="dashboard-item-description-submit"
                            >
                                Save changes
                            </Button>
                        ) : (
                            <Button
                                style={{ marginRight: 16 }}
                                onClick={() => setDashboardItemMode(DashboardItemMode.Edit)}
                            >
                                <EditOutlined />
                                Edit name or description
                            </Button>
                        ))}
                </div>
            </div>
        </div>
    )
}
