import React from 'react'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { Col, Row } from 'antd'
import { resetKeaStory } from 'lib/storybook/kea-story'
import { Provider } from 'kea'
import { defaultHistoryMocks, emptyHistoryMocks } from 'lib/components/HistoryList/historyMocks'

export default {
    title: 'PostHog/Components/HistoryList',
}

export const WithData = (): JSX.Element => {
    resetKeaStory()
    defaultHistoryMocks()

    return (
        <Provider>
            <Row>
                <Col span={24}>
                    <HistoryList type={'feature_flags'} id={7} />
                </Col>
            </Row>
        </Provider>
    )
}

export const WithNoData = (): JSX.Element => {
    resetKeaStory()
    emptyHistoryMocks()

    return (
        <Provider>
            <Row>
                <HistoryList type={'feature_flags'} id={6} />
            </Row>
        </Provider>
    )
}
