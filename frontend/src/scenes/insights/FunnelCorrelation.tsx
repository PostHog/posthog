import { Button, Card, Row, Col } from 'antd'
import { CommentOutlined } from '@ant-design/icons'
import TextArea from 'antd/lib/input/TextArea'
import { useActions, useValues } from 'kea'
import React, { useRef } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from './insightLogic'
import './FunnelCorrelation.scss'
import { FunnelCorrelationTable } from './InsightTabs/FunnelTab/FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './InsightTabs/FunnelTab/FunnelPropertyCorrelationTable'
import { IconFeedbackWarning } from 'lib/components/icons'
import { CloseOutlined } from '@ant-design/icons'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const {
        isSkewed,
        stepsWithCount,
        correlationFeedbackHidden,
        correlationDetailedFeedbackVisible,
        correlationFeedbackRating,
    } = useValues(funnelLogic(insightProps))
    const {
        sendCorrelationAnalysisFeedback,
        hideSkewWarning,
        hideCorrelationAnalysisFeedback,
        setCorrelationFeedbackRating,
        setCorrelationDetailedFeedback,
    } = useActions(funnelLogic(insightProps))

    const detailedFeedbackRef = useRef<HTMLTextAreaElement>(null)

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

            <FunnelCorrelationTable />

            {/* Feedback Form */}
            {!correlationFeedbackHidden && (
                <Card className="correlation-feedback">
                    <Row className="row-initial">
                        <Col span={15}>
                            <h4>
                                <CommentOutlined style={{ marginRight: 4 }} />
                                Was this correlation analysis report useful?
                            </h4>
                        </Col>
                        <Col span={8} style={{ alignContent: 'right' }}>
                            {!!correlationFeedbackRating && (
                                <i style={{ color: 'var(--success)', marginRight: 8 }}>Thanks for your feedback!</i>
                            )}
                            {(
                                [
                                    [5, '😍'],
                                    [4, '😀'],
                                    [3, '😴'],
                                    [2, '😔'],
                                    [1, '👎'],
                                ] as const
                            ).map((content, index) => (
                                <Button
                                    key={index}
                                    className="emoji-button"
                                    style={
                                        correlationFeedbackRating === content[0]
                                            ? { background: '#5375FF' }
                                            : correlationFeedbackRating
                                            ? { display: 'none' }
                                            : {}
                                    }
                                    onClick={() => {
                                        if (correlationFeedbackRating === content[0]) {
                                            setCorrelationFeedbackRating(0)
                                        } else {
                                            setCorrelationFeedbackRating(content[0])
                                            setTimeout(() => detailedFeedbackRef.current?.focus(), 100)
                                        }
                                    }}
                                >
                                    {content[1]}
                                </Button>
                            ))}
                        </Col>
                        <Col span={1}>
                            <CloseOutlined className="close-button" onClick={hideCorrelationAnalysisFeedback} />
                        </Col>
                    </Row>

                    <div style={{ display: correlationDetailedFeedbackVisible ? undefined : 'none' }}>
                        <TextArea
                            onBlur={(e) => setCorrelationDetailedFeedback(e.target.value)}
                            placeholder="Optional. Help us by sharing details around your experience..."
                            style={{ marginTop: 16 }}
                            ref={detailedFeedbackRef}
                        />
                        <div className="text-right">
                            <Button
                                className="feedback-button"
                                data-attr="correlation-analysis-share-feedback"
                                type="primary"
                                onClick={() => {
                                    sendCorrelationAnalysisFeedback()
                                }}
                            >
                                Share feedback
                            </Button>
                        </div>
                    </div>
                </Card>
            )}

            <FunnelPropertyCorrelationTable />
        </div>
    )
}
