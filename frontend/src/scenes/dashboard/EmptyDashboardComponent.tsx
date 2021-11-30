import { Col, Row, Skeleton, Card } from 'antd'
import { HotkeyButton } from 'lib/components/HotkeyButton/HotkeyButton'
import React from 'react'
import { PlusOutlined } from '@ant-design/icons'
import { dashboardLogic } from './dashboardLogic'
import { useActions } from 'kea'

function SkeletonOne(): JSX.Element {
    return (
        <Card className="hide-lte-lg">
            <Row>
                <Col span={12}>
                    <Skeleton paragraph={{ rows: 1 }} />
                    <div className="mt">
                        <div className="mt">
                            <Skeleton.Button />
                            <Skeleton.Button style={{ marginLeft: 4, width: 140 }} />
                        </div>
                        <div className="mt">
                            <Skeleton.Button />
                            <Skeleton.Button style={{ marginLeft: 4, width: 140 }} />
                        </div>
                        <div className="mt">
                            <Skeleton.Button />
                            <Skeleton.Button style={{ marginLeft: 4, width: 140 }} />
                        </div>
                    </div>
                </Col>
                <Col span={12}>
                    <div className="skeleton-actions">
                        <Skeleton.Avatar shape="circle" size="small" />
                        <Skeleton.Avatar shape="circle" size="small" />
                    </div>
                    <Skeleton.Avatar shape="circle" size="large" className="pie-chart" />
                </Col>
            </Row>
        </Card>
    )
}

function SkeletonTwo(): JSX.Element {
    return (
        <Card>
            <Row>
                <Col span={12}>
                    <Skeleton paragraph={{ rows: 1 }} />
                </Col>
                <Col span={12}>
                    <div className="skeleton-actions">
                        <Skeleton.Avatar shape="circle" size="small" />
                        <Skeleton.Avatar shape="circle" size="small" />
                    </div>
                </Col>
            </Row>
            <div className="bar-chart">
                {Array(8)
                    .fill(0)
                    .map((_, index) => {
                        const max = 200
                        const min = 40
                        const height = Math.floor(Math.random() * (max - min + 1)) + min
                        return <div className="bar-el" key={index} style={{ height: height }} />
                    })}
            </div>
        </Card>
    )
}

export function EmptyDashboardComponent(): JSX.Element {
    const { addGraph } = useActions(dashboardLogic)

    return (
        <div className="empty-state">
            <div className="cta">
                <Card className="card-elevated">
                    <h3 className="l3">Dashboard empty</h3>
                    <p>This dashboard sure would look better with some graphs!</p>
                    <div className="mt text-center">
                        <HotkeyButton
                            onClick={() => addGraph()}
                            data-attr="dashboard-add-graph-header"
                            icon={<PlusOutlined />}
                            hotkey="n"
                        >
                            Add graph
                        </HotkeyButton>
                    </div>
                </Card>
            </div>
            <Row gutter={16}>
                <Col span={24} lg={12}>
                    <SkeletonOne />
                </Col>
                <Col span={24} lg={12}>
                    <SkeletonTwo />
                </Col>
            </Row>
            <Row gutter={16} className="fade-out-graphs">
                <Col span={24} lg={12}>
                    <SkeletonOne />
                </Col>
                <Col span={24} lg={12}>
                    <SkeletonTwo />
                </Col>
            </Row>
        </div>
    )
}
