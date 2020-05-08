import './DashboardHeader.scss'

import { Loading } from 'lib/utils'
import { Button, Dropdown, Menu, Select } from 'antd'
import { router } from 'kea-router'
import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { PushpinFilled, PushpinOutlined, EllipsisOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { newDashboardLogic } from './newDashboardLogic'

export function DashboardHeader({ logic, id }) {
    const { dashboard } = useValues(logic)
    const { renameDashboard } = useActions(logic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const { addNewDashboard } = useActions(newDashboardLogic({ key: `dashboard-${id}`, redirect: true }))

    return (
        <div className="dashboard-header">
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    <div>
                        <Select
                            value={dashboard?.id || null}
                            onChange={id =>
                                id === 'new' ? addNewDashboard() : router.actions.push(`/dashboard/${id}`)
                            }
                            bordered={false}
                            dropdownMatchSelectWidth={false}
                        >
                            {!dashboard ? <Select.Option value={null}>Not Found</Select.Option> : null}
                            {dashboards.map(dash => (
                                <Select.Option key={dash.id} value={parseInt(dash.id)}>
                                    {dash.name || <span style={{ color: 'var(--gray)' }}>Untitled</span>}
                                </Select.Option>
                            ))}

                            <Select.Option value="new">+ New Dashboard</Select.Option>
                        </Select>
                    </div>
                    {dashboard ? (
                        <div className="dashboard-meta">
                            <Button
                                type={dashboard.pinned ? 'primary' : ''}
                                onClick={() =>
                                    dashboard.pinned ? unpinDashboard(dashboard.id) : pinDashboard(dashboard.id)
                                }
                            >
                                {dashboard.pinned ? <PushpinFilled /> : <PushpinOutlined />} Pin
                            </Button>

                            <Dropdown
                                trigger="click"
                                overlay={
                                    <Menu>
                                        <Menu.Item icon={<EditOutlined />} onClick={renameDashboard}>
                                            Rename "{dashboard.name}"
                                        </Menu.Item>
                                        <Menu.Item
                                            icon={<DeleteOutlined />}
                                            onClick={() => deleteDashboard(dashboard.id)}
                                            className="text-danger"
                                        >
                                            Delete
                                        </Menu.Item>
                                    </Menu>
                                }
                                placement="bottomRight"
                            >
                                <Button className="button-box">
                                    <EllipsisOutlined />
                                </Button>
                            </Dropdown>
                        </div>
                    ) : null}
                </>
            )}
        </div>
    )
}
