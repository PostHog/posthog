import { Button, Card, Row, Col } from 'antd'
import { CommentOutlined } from '@ant-design/icons'
import TextArea from 'antd/lib/input/TextArea'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from './insightLogic'
import './FunnelCorrelation.scss'
import { FunnelCorrelationTable } from './InsightTabs/FunnelTab/FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './InsightTabs/FunnelTab/FunnelPropertyCorrelationTable'
import { IconFeedbackWarning } from 'lib/components/icons'
import { CloseOutlined } from '@ant-design/icons'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed, stepsWithCount, correlationFeedbackHidden } = useValues(funnelLogic(insightProps))
    const { sendCorrelationAnalysisFeedback, hideSkewWarning, hideCorrelationAnalysisFeedback } = useActions(
        funnelLogic(insightProps)
    )

    const [modalVisible, setModalVisible] = useState(false)
    const [rating, setRating] = useState(0)
    const [detailedFeedback, setDetailedFeedback] = useState('')

    if (stepsWithCount.length <= 1) {
        return null
    }

    return (
        <div className="funnel-correlation">
            {isSkewed && (
                <Card className="skew-warning">
                    <h4>
                        <IconFeedbackWarning style={{ fontSize: 24, marginRight: 4, color: 'var(--warning)' }} /> Adjust
                        your funnel definition to improve correlation analysis
                        <CloseOutlined className="close-button" onClick={hideSkewWarning} />
                    </h4>
                    <div>
                        <b>Tips for adjusting your funnel:</b>
                        <ol>
                            <li>
                                Adjust your first funnel step to be more specific. For example, choose a page or an
                                event that occurs less frequently.
                            </li>
                            <li>Choose an event that happens more frequently for subsequent funnels steps.</li>
                        </ol>
                    </div>
                </Card>
            )}

            {/* Feedback Form */}
            {!correlationFeedbackHidden && (
                <Card className="correlation-feedback">
                    <h4>
                        <CloseOutlined className="close-button" onClick={hideCorrelationAnalysisFeedback} />
                        <Row>
                            <Col span={16}>
                                <CommentOutlined style={{ paddingRight: 8 }} />
                                Is the new feature, Corrrelation analysis, working well for you?
                            </Col>
                            <Col span={8} style={{ alignContent: 'right' }}>
                                <Button
                                    className="emoji-button"
                                    style={rating === 1 ? { background: '#5375FF' } : {}}
                                    onClick={() => {
                                        setRating(1)
                                        setModalVisible(true)
                                    }}
                                >
                                    😍
                                </Button>
                                <Button
                                    className="emoji-button"
                                    style={rating === 2 ? { background: '#5375FF' } : {}}
                                    onClick={() => {
                                        setRating(2)
                                        setModalVisible(true)
                                    }}
                                >
                                    😀
                                </Button>
                                <Button
                                    className="emoji-button"
                                    style={rating === 3 ? { background: '#5375FF' } : {}}
                                    onClick={() => {
                                        setRating(3)
                                        setModalVisible(true)
                                    }}
                                >
                                    😴
                                </Button>
                                <Button
                                    className="emoji-button"
                                    style={rating === 4 ? { background: '#5375FF' } : {}}
                                    onClick={() => {
                                        setRating(4)
                                        setModalVisible(true)
                                    }}
                                >
                                    👎
                                </Button>
                                <Button
                                    className="emoji-button"
                                    style={rating === 5 ? { background: '#5375FF' } : {}}
                                    onClick={() => {
                                        setRating(5)
                                        setModalVisible(true)
                                    }}
                                >
                                    👍
                                </Button>
                            </Col>
                        </Row>
                    </h4>
                    <div style={{ display: modalVisible ? undefined : 'None' }}>
                        <hr />
                        Tell us more <i>(optional)</i>
                        <TextArea onBlur={(e) => setDetailedFeedback(e.target.value)} />
                        <Button
                            className="feedback-button"
                            onClick={() => {
                                setModalVisible(false)
                                setRating(0)
                            }}
                        >
                            Cancel
                        </Button>
                        <Button
                            className="feedback-button"
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
            )}

            <FunnelCorrelationTable />
            <FunnelPropertyCorrelationTable />
        </div>
    )
}
