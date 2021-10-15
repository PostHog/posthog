import { Button, Card, Row, Col } from 'antd'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from './insightLogic'
import { CommentOutlined, WarningOutlined } from '@ant-design/icons'

import { FunnelCorrelationTable } from './InsightTabs/FunnelTab/FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './InsightTabs/FunnelTab/FunnelPropertyCorrelationTable'
import TextArea from 'antd/lib/input/TextArea'

export const FunnelCorrelation = (): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed, stepsWithCount } = useValues(funnelLogic(insightProps))
    const { sendCorrelationAnalysisFeedback } = useActions(funnelLogic(insightProps))

    const [modalVisible, setModalVisible] = useState(false)
    const [rating, setRating] = useState(0)
    const [detailedFeedback, setDetailedFeedback] = useState('')

    return stepsWithCount.length > 1 ? (
        <>
            {isSkewed ? (
                <Card style={{ marginTop: '1em' }}>
                    <div style={{ alignItems: 'center' }}>
                        <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                        <b>Funnel skewed!</b>
                        <br />
                        Your funnel has a large skew to either successes or failures. With such funnels it's hard to get
                        meaningful odds for events and property correlations. Try adjusting your funnel to have a more
                        balanced success/failure ratio.
                    </div>
                </Card>
            ) : null}

            {/* Feedback Form */}
            <Card style={{ marginTop: '1em', alignItems: 'center', borderRadius: 4 }}>
                <div style={{ fontWeight: 600, fontSize: '14px' }}>
                    <Row>
                        <Col span={16}>
                            <CommentOutlined style={{ paddingRight: 8 }} />
                            Is the new feature, Corrrelation analysis, working well for you?
                        </Col>
                        <Col span={8} style={{ alignContent: 'right' }}>
                            <Button
                                style={rating === 1 ? { background: '#5375FF' } : {}}
                                onClick={() => {
                                    setRating(1)
                                    setModalVisible(true)
                                }}
                            >
                                😍
                            </Button>
                            <Button
                                className={rating === 2 ? 'emoji-button-selected' : ''}
                                onClick={() => {
                                    setRating(2)
                                    setModalVisible(true)
                                }}
                            >
                                😀
                            </Button>
                            <Button
                                className={rating === 3 ? 'emoji-button-selected' : ''}
                                onClick={() => {
                                    setRating(3)
                                    setModalVisible(true)
                                }}
                            >
                                😴
                            </Button>
                            <Button
                                className={rating === 4 ? 'emoji-button-selected' : ''}
                                onClick={() => {
                                    setRating(4)
                                    setModalVisible(true)
                                }}
                            >
                                👎
                            </Button>
                            <Button
                                className={rating === 5 ? 'emoji-button-selected' : ''}
                                onClick={() => {
                                    setRating(5)
                                    setModalVisible(true)
                                }}
                            >
                                👍
                            </Button>
                        </Col>
                    </Row>
                </div>
                <div style={{ display: modalVisible ? undefined : 'None' }}>
                    <hr />
                    Tell us more <i>(optional)</i>
                    <TextArea onBlur={(e) => setDetailedFeedback(e.target.value)} />
                    <Button
                        onClick={() => {
                            setModalVisible(false)
                            setRating(0)
                        }}
                    >
                        Cancel
                    </Button>
                    <Button
                        type="primary"
                        onClick={() => {
                            sendCorrelationAnalysisFeedback(rating, detailedFeedback)
                            setModalVisible(false)
                            setRating(0)
                        }}
                    >
                        Share Feedback
                    </Button>
                </div>
            </Card>

            <FunnelCorrelationTable />
            <FunnelPropertyCorrelationTable />
        </>
    ) : (
        <></>
    )
}
