import { Card, Col, Row, Skeleton } from 'antd'
import { kea, useValues } from 'kea'
import { router, combineUrl } from 'kea-router'
import api from 'lib/api'
import { NotFound } from 'lib/components/NotFound'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { DashboardItemType } from '~/types'
import { insightRouterLogicType } from './InsightRouterType'

const insightRouterLogic = kea<insightRouterLogicType>({
    actions: {
        loadInsight: (id: string) => ({ id }),
        setError: true,
    },
    reducers: {
        error: [
            false,
            {
                setError: () => true,
            },
        ],
    },
    listeners: ({ actions }) => ({
        loadInsight: async ({ id }) => {
            const response = await api.get(`api/insight/?short_id=${id}`)
            if (response.results.length) {
                const item = response.results[0] as DashboardItemType
                eventUsageLogic.actions.reportInsightShortUrlVisited(true, item.filters.insight || null)
                router.actions.push(
                    combineUrl('/insights', item.filters, {
                        fromItem: item.id,
                        fromItemName: item.name,
                        fromDashboard: item.dashboard,
                        id: item.short_id,
                    }).url
                )
            } else {
                eventUsageLogic.actions.reportInsightShortUrlVisited(false, null)
                actions.setError()
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/i/:id': ({ id }) => {
            if (id) {
                actions.loadInsight(id)
            }
        },
    }),
})

/* Handles insights short links `/i/{id}` */
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
