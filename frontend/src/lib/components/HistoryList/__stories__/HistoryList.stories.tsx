import React from 'react'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { Col, Row } from 'antd'
import { resetKeaStory } from 'lib/storybook/kea-story'
import { Provider } from 'kea'
import { defaultHistoryMocks, emptyHistoryMocks } from 'lib/components/HistoryList/__stories__/historyMocks'

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
                    <HistoryList type={'FeatureFlag'} id={7} />
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
                <HistoryList type={'FeatureFlag'} id={6} />
            </Row>
        </Provider>
    )
}

export const WithNoID = (): JSX.Element => {
    resetKeaStory()
    emptyHistoryMocks()

    return (
        <Provider>
            <Row>
                <HistoryList type={'FeatureFlag'} id={null} />
            </Row>
        </Provider>
    )
}
