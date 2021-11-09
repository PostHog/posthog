import { Card, Col, Row, Skeleton } from 'antd'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { insightRouterLogic } from 'scenes/insights/insightRouterLogic'

/* Handles insights links `/i/{id}` and `/insights/new` */
export function InsightRouter(): JSX.Element {
    const { error } = useValues(insightRouterLogic)
    return (
        <>
            {error ? (
                <NotFound object="insight" />
            ) : (
                <>
                    <Skeleton active paragraph={{ rows: 0 }} />
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
            )}
        </>
    )
}

export const scene: SceneExport = {
    component: InsightRouter,
    logic: insightRouterLogic,
}
