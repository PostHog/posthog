import { Col, Row, Skeleton, Card } from 'antd'
import React from 'react'

function SkeletonOne(): JSX.Element {
    return (
        <Card>
            <Row>
                <Col span={12}>
                    <Skeleton paragraph={{ rows: 1 }} />
                    <div className="mt hide-lte-lg">
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

export function EmptyDashboardComponent(): JSX.Element {
    return (
        <div className="empty-state">
            <Row>
                <Col span={24} lg={12}>
                    <SkeletonOne />
                </Col>
            </Row>
        </div>
    )
}
