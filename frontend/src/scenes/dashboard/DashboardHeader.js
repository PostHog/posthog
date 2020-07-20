import './DashboardHeader.scss'

import { Loading, triggerResizeAfterADelay } from 'lib/utils'
import { Button, Dropdown, Menu, Select, Tooltip, Row, Col, Modal } from 'antd'
import { router } from 'kea-router'
import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ShareModal } from './ShareModal'
import {
    PushpinFilled,
    PushpinOutlined,
    EllipsisOutlined,
    EditOutlined,
    DeleteOutlined,
    FullscreenOutlined,
    FullscreenExitOutlined,
    LockOutlined,
    UnlockOutlined,
    ShareAltOutlined,
    PlusOutlined,
    FunnelPlotOutlined,
    RiseOutlined,
} from '@ant-design/icons'
import { FullScreen } from 'lib/components/FullScreen'
import { Card } from '../../lib/utils'

export function DashboardHeader({ logic }) {
    const { dashboard, draggingEnabled } = useValues(logic)
    const { addNewDashboard, renameDashboard, enableDragging, disableDragging } = useActions(logic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const [fullScreen, setFullScreen] = useState(false)
    const [showShareModal, setShowShareModal] = useState(false)
    const [isAddItemModalVisible, setIsAddItemModalVisible] = useState(false)

    return (
        <div className={`dashboard-header${fullScreen ? ' full-screen' : ''}`}>
            {fullScreen ? <FullScreen onExit={() => setFullScreen(false)} /> : null}
            {showShareModal && <ShareModal logic={logic} onCancel={() => setShowShareModal(false)} />}
            {dashboardsLoading ? (
                <Loading />
            ) : (
                <>
                    <div className="dashboard-select">
                        <Select
                            value={dashboard?.id || null}
                            onChange={(id) =>
                                id === 'new' ? addNewDashboard() : router.actions.push(`/dashboard/${id}`)
                            }
                            bordered={false}
                            dropdownMatchSelectWidth={false}
                        >
                            {!dashboard ? <Select.Option value={null}>Not Found</Select.Option> : null}
                            {dashboards.map((dash) => (
                                <Select.Option key={dash.id} value={parseInt(dash.id)}>
                                    {dash.name || <span style={{ color: 'var(--gray)' }}>Untitled</span>}
                                </Select.Option>
                            ))}

                            <Select.Option value="new">+ New Dashboard</Select.Option>
                        </Select>
                    </div>
                    {dashboard ? (
                        <div className="dashboard-meta">
                            <Button type="primary" onClick={() => setIsAddItemModalVisible(true)}>
                                <PlusOutlined />
                                <span className="hide-when-small">Add Item</span>
                            </Button>
                            {!fullScreen ? (
                                <Tooltip title={dashboard.pinned ? 'Pinned into sidebar' : 'Pin into sidebar'}>
                                    <Button
                                        className="button-box-when-small"
                                        type={dashboard.pinned ? 'primary' : ''}
                                        onClick={() =>
                                            dashboard.pinned ? unpinDashboard(dashboard.id) : pinDashboard(dashboard.id)
                                        }
                                    >
                                        {dashboard.pinned ? <PushpinFilled /> : <PushpinOutlined />}
                                        <span className="hide-when-small">{dashboard.pinned ? 'Pinned' : 'Pin'}</span>
                                    </Button>
                                </Tooltip>
                            ) : null}

                            <Tooltip title={'Share dashboard.'}>
                                <Button
                                    className="button-box-when-small enable-dragging-button"
                                    type={dashboard.is_shared ? 'primary' : ''}
                                    onClick={() => setShowShareModal(true)}
                                    data-attr="dashboard-share-button"
                                >
                                    <ShareAltOutlined />
                                    <span className="hide-when-small">
                                        {dashboard.is_shared ? 'Shared' : 'Share dashboard'}
                                    </span>
                                </Button>
                            </Tooltip>

                            <Tooltip title="Click here or long press on a panel to rearrange the dashboard.">
                                <Button
                                    className="button-box enable-dragging-button"
                                    type={draggingEnabled === 'off' ? 'primary' : ''}
                                    onClick={draggingEnabled === 'off' ? enableDragging : disableDragging}
                                >
                                    {draggingEnabled !== 'off' ? <UnlockOutlined /> : <LockOutlined />}
                                </Button>
                            </Tooltip>

                            <Tooltip title={fullScreen ? 'Presentation Mode Activated' : 'Activate Presentation Mode'}>
                                <Button
                                    className="button-box"
                                    onClick={() => {
                                        setFullScreen(!fullScreen)
                                        triggerResizeAfterADelay()
                                    }}
                                >
                                    {fullScreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                                </Button>
                            </Tooltip>

                            {!fullScreen ? (
                                <Dropdown
                                    trigger="click"
                                    overlay={
                                        <Menu>
                                            <Menu.Item icon={<EditOutlined />} onClick={renameDashboard}>
                                                Rename "{dashboard.name}"
                                            </Menu.Item>
                                            <Menu.Item
                                                icon={<DeleteOutlined />}
                                                onClick={() => deleteDashboard({ id: dashboard.id, redirect: true })}
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
                            ) : null}
                        </div>
                    ) : null}
                </>
            )}
            <Modal
                visible={isAddItemModalVisible}
                style={{ cursor: 'pointer' }}
                onCancel={() => {
                    setIsAddItemModalVisible(false)
                }}
                title="Create dashboard item"
                footer={[
                    <Button
                        key="cancel-button"
                        onClick={() => {
                            setIsAddItemModalVisible(false)
                        }}
                    >
                        Cancel
                    </Button>,
                ]}
            >
                {
                    <Row gutter={2} justify="space-between">
                        <Col xs={11}>
                            <Card
                                title="Trend Graph"
                                onClick={() => router.actions.push('/trends')}
                                size="small"
                                style={{ marginBottom: 0 }}
                            >
                                <div style={{ textAlign: 'center', fontSize: 60 }}>
                                    <RiseOutlined />
                                </div>
                            </Card>
                        </Col>
                        <Col xs={11}>
                            <Card
                                title="Funnel Visualization"
                                onClick={() => {
                                    router.actions.push('/funnel')
                                }}
                                size="small"
                                style={{ marginBottom: 0 }}
                            >
                                <div style={{ textAlign: 'center', fontSize: 60 }} data-attr="new-action-pageview">
                                    <FunnelPlotOutlined />
                                </div>
                            </Card>
                        </Col>
                    </Row>
                }
            </Modal>
        </div>
    )
}
