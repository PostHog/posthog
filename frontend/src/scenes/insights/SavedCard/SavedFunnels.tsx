import React from 'react'
import { useValues, useActions } from 'kea'
import { funnelsModel } from '~/models/funnelsModel'
import { List, Col, Row, Spin, Button } from 'antd'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'

export const SavedFunnels: React.FC = () => {
    const { funnels, funnelsLoading, next, loadingMore } = useValues(funnelsModel)
    const { loadNext } = useActions(funnelsModel)

    const loadMoreFunnels = next ? (
        <div
            style={{
                textAlign: 'center',
                marginTop: 12,
                height: 32,
                lineHeight: '32px',
            }}
        >
            {loadingMore ? <Spin /> : <Button onClick={loadNext}>Load more</Button>}
        </div>
    ) : null

    return (
        <List
            loading={funnelsLoading}
            dataSource={funnels}
            loadMore={loadMoreFunnels}
            pagination={{ pageSize: 5, hideOnSinglePage: true }}
            renderItem={(funnel) => {
                return (
                    <List.Item>
                        <Col style={{ whiteSpace: 'pre-line', width: '100%' }}>
                            <Row justify="space-between" align="middle">
                                <Link to={'/insights?' + toParams(funnel.filters)}>{funnel.name}</Link>
                            </Row>
                        </Col>
                    </List.Item>
                )
            }}
        />
    )
}
