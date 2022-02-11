import React from 'react'
import { HistoryList } from 'lib/components/HistoryList'
import { Col, Row } from 'antd'
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
                                email: 'paul@posthog.com',
                                name: 'paul',
                                description: 'created a new user: john',
                                created_at: now().subtract(3, 'days'),
                            },
                            {
                                email: 'john@posthog.com',
                                name: 'john',
                                description: 'created a new insight Page Views per nanosecond',
                                created_at: now().subtract(3, 'days'),
                            },
                            {
                                email: 'tim@posthog.com',
                                name: 'tim',
                                description: "changed john's name to jane",
                                created_at: now().subtract(2, 'days'),
                            },
                            {
                                email: 'jane@posthog.com',
                                name: 'jane',
                                description: 'added tags to an insight',
                                created_at: now().subtract(1, 'hour'),
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
