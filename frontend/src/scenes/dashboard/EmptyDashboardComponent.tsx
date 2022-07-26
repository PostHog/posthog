import { Col, Row, Skeleton, Card, SkeletonProps } from 'antd'
import React from 'react'
import { dashboardLogic } from './dashboardLogic'
import { useValues } from 'kea'
import clsx from 'clsx'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { LemonButton } from 'lib/components/LemonButton'

function SkeletonCardOne({ active }: Pick<SkeletonProps, 'active'>): JSX.Element {
    return (
        <Card className="hide-lte-lg">
            <Row>
                <Col span={12}>
                    <Skeleton paragraph={{ rows: 1 }} active={active} />
                    <div className="mt-4">
                        <div className="mt-4">
                            <Skeleton.Button active={active} />
                            <Skeleton.Button active={active} style={{ marginLeft: 4, width: 140 }} />
                        </div>
                        <div className="mt-4">
                            <Skeleton.Button active={active} />
                            <Skeleton.Button active={active} style={{ marginLeft: 4, width: 140 }} />
                        </div>
                        <div className="mt-4">
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

function SkeletonBarsRaw(): JSX.Element {
    return (
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
    )
}
/** This component looks different on each render due to Math.random() calls within, so it's memoized to avoid that. */
const SkeletonBars = React.memo(SkeletonBarsRaw)

function SkeletonCardTwo({ active }: Pick<SkeletonProps, 'active'>): JSX.Element {
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
            <SkeletonBars />
        </Card>
    )
}

export function EmptyDashboardComponent({ loading }: { loading: boolean }): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)

    return (
        <div className="empty-state">
            {!loading && (
                <div className="cta">
                    <Card className="card-elevated">
                        <h3 className="l3">Dashboard empty</h3>
                        <p>This dashboard sure would look better with some graphs!</p>
                        <div className="mt-4 text-center">
                            <Link to={urls.insightNew(undefined, dashboard?.id)}>
                                <LemonButton data-attr="dashboard-add-graph-header">Add insight</LemonButton>
                            </Link>
                        </div>
                    </Card>
                </div>
            )}
            <Row gutter={16}>
                <Col span={24} lg={12}>
                    <SkeletonCardOne active={loading} />
                </Col>
                <Col span={24} lg={12}>
                    <SkeletonCardTwo active={loading} />
                </Col>
            </Row>
            <Row gutter={16} className="fade-out-graphs">
                <Col span={24} lg={12}>
                    <SkeletonCardOne active={loading} />
                </Col>
                <Col span={24} lg={12}>
                    <SkeletonCardTwo active={loading} />
                </Col>
            </Row>
        </div>
    )
}
