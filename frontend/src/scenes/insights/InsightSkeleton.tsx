import React from 'react'
import { Card, Col, Row, Skeleton } from 'antd'

export function InsightSkeleton(): JSX.Element {
    return (
        <>
            <Skeleton active title paragraph={{ rows: 3 }} className="page-title-row page-caption mb-025" />
            <Skeleton active title={false} paragraph={{ rows: 1 }} />
            <Card>
                <Row gutter={16}>
                    <Col md={18}>
                        <Skeleton active />
                    </Col>
                    <Col md={6} style={{ textAlign: 'center' }}>
                        <Skeleton active paragraph={{ rows: 0 }} />
                        <Skeleton active paragraph={{ rows: 0 }} />
                        <Skeleton active paragraph={{ rows: 0 }} />
                    </Col>
                </Row>
            </Card>
            <Card style={{ minHeight: 600, marginTop: 16 }} />
        </>
    )
}
