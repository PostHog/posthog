import React from 'react'
import { useValues, useActions } from 'kea'
import { funnelsModel } from '~/models/funnelsModel'
import { List, Col, Row, Button, Popconfirm } from 'antd'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'

export function SavedFunnels(): JSX.Element {
    const { funnels, funnelsLoading, next, loadingMore } = useValues(funnelsModel)
    const { deleteFunnel, loadNext } = useActions(funnelsModel)

    const loadMoreFunnels = next ? (
        <div
            style={{
                textAlign: 'center',
                marginTop: 12,
                height: 32,
                lineHeight: '32px',
            }}
        >
            <Button onClick={loadNext} loading={loadingMore}>
                Load more
            </Button>
        </div>
    ) : null

    return (
        <List
            loading={funnelsLoading}
            dataSource={funnels}
            loadMore={loadMoreFunnels}
            renderItem={(funnel) => {
                return (
                    <List.Item>
                        <Col style={{ whiteSpace: 'pre-line', width: '100%', padding: 0 }}>
                            <Row justify="space-between" align="middle">
                                <Link to={'/insights?' + toParams(funnel.filters)} style={{ flex: 1 }}>
                                    {funnel.name}
                                </Link>
                                <Popconfirm
                                    title={`Delete saved funnel "${funnel.name}"?`}
                                    okText="Delete Funnel"
                                    okType="danger"
                                    icon={<ExclamationCircleOutlined style={{ color: red.primary }} />}
                                    placement="left"
                                    onConfirm={() => {
                                        deleteFunnel(funnel.id)
                                    }}
                                >
                                    <DeleteOutlined className="text-danger" />
                                </Popconfirm>
                            </Row>
                        </Col>
                    </List.Item>
                )
            }}
        />
    )
}
