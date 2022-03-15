import { Col, Row, Skeleton, Card, SkeletonProps } from 'antd'
import { HotkeyButton } from 'lib/components/HotkeyButton/HotkeyButton'
import React from 'react'
import { PlusOutlined } from '@ant-design/icons'
import { dashboardLogic } from './dashboardLogic'
import { useActions } from 'kea'
import clsx from 'clsx'

function SkeletonOne({ active }: Pick<SkeletonProps, 'active'>): JSX.Element {
    return (
        <Card className="hide-lte-lg">
            <Row>
                <Col span={12}>
                    <Skeleton paragraph={{ rows: 1 }} active={active} />
                    <div className="mt">
                        <div className="mt">
                            <Skeleton.Button active={active} />
                            <Skeleton.Button active={active} style={{ marginLeft: 4, width: 140 }} />
                        </div>
                        <div className="mt">
                            <Skeleton.Button active={active} />
                            <Skeleton.Button active={active} style={{ marginLeft: 4, width: 140 }} />
                        </div>
                        <div className="mt">
                            <Skeleton.Button active={active} />
                            <Skeleton.Button active={active} style={{ marginLeft: 4, width: 140 }} />
                        </div>
                    </div>
                </Col>
                <Col span={12}>
                    <div className="skeleton-actions">
                        <Skeleton.Avatar active={active} shape="circle" size="small" />
                        <Skeleton.Avatar active={active} shape="circle" size="small" />
                    </div>
                    <Skeleton.Avatar active={active} shape="circle" size="large" className="pie-chart" />
                </Col>
            </Row>
        </Card>
    )
}

function SkeletonTwo({ active }: Pick<SkeletonProps, 'active'>): JSX.Element {
    return (
        <Card className={clsx('ant-skeleton', active && 'ant-skeleton-active')}>
            <Row>
                <Col span={12}>
                    <Skeleton active={active} paragraph={{ rows: 1 }} />
                </Col>
                <Col span={12}>
                    <div className="skeleton-actions">
                        <Skeleton.Avatar active={active} shape="circle" size="small" />
                        <Skeleton.Avatar active={active} shape="circle" size="small" />
                    </div>
                </Col>
            </Row>
            <div className="bar-chart ant-skeleton-content">
                {Array(8)
                    .fill(0)
                    .map((_, index) => {
                        const max = 200
                        const min = 40
                        const height = Math.floor(Math.random() * (max - min + 1)) + min
                        return <div className="bar-el ant-skeleton-title" key={index} style={{ height: height }} />
                    })}
            </div>
        </Card>
    )
}

export function EmptyDashboardComponent({ loading }: { loading: boolean }): JSX.Element {
    const { addGraph } = useActions(dashboardLogic)

    return (
        <div className="empty-state">
            {!loading && (
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
                                New insight
                            </HotkeyButton>
                        </div>
                    </Card>
                </div>
            )}
            <Row gutter={16}>
                <Col span={24} lg={12}>
                    <SkeletonOne active={loading} />
                </Col>
                <Col span={24} lg={12}>
                    <SkeletonTwo active={loading} />
                </Col>
            </Row>
            <Row gutter={16} className="fade-out-graphs">
                <Col span={24} lg={12}>
                    <SkeletonOne active={loading} />
                </Col>
                <Col span={24} lg={12}>
                    <SkeletonTwo active={loading} />
                </Col>
            </Row>
        </div>
    )
}
