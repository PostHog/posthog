import React from 'react'
import { HistoryList } from 'lib/components/HistoryList'
import { Col, Row, Tag } from 'antd'
import { KeaStory } from 'lib/storybook/kea-story'
import { now } from 'lib/dayjs'

export default {
    title: 'PostHog/Components/HistoryList',
}

export function WithData(): JSX.Element {
    return (
        <KeaStory>
            <Row>
                <Col span={24}>
                    <HistoryList
                        history={[
                            {
                                email: 'kunal@posthog.com',
                                name: 'kunal',
                                description: 'modified the insight description',
                                created_at: now().subtract(3, 'days'),
                            },
                            {
                                email: 'eli@posthog.com',
                                name: 'eli',
                                description: (
                                    <>
                                        added this insight to <a>My Dashboard</a>
                                    </>
                                ),
                                created_at: now().subtract(2, 'days'),
                            },
                            {
                                email: 'guido@posthog.com',
                                name: 'guido',
                                description: 'shared this dashboard',
                                created_at: now().subtract(1, 'hour'),
                            },
                            {
                                description: 'shared the insight',
                                created_at: now().subtract(35, 'minutes'),
                            },
                            {
                                email: 'paul@posthog.com',
                                name: 'paul',
                                description: (
                                    <>
                                        added the tags <Tag>hogflix</Tag> <Tag>demo</Tag> <Tag>offical</Tag>{' '}
                                        <Tag>tag</Tag>
                                    </>
                                ),
                                created_at: now().subtract(5, 'minutes'),
                            },
                        ]}
                    />
                </Col>
            </Row>
        </KeaStory>
    )
}

export function WithNoData(): JSX.Element {
    return (
        <KeaStory>
            <Row>
                <HistoryList history={[]} />
            </Row>
        </KeaStory>
    )
}
