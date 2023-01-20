import { Card } from 'antd'
import { CommentOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import './FunnelCorrelation.scss'
import { IconClose, IconFeedbackWarning } from 'lib/components/icons'
import { CloseOutlined } from '@ant-design/icons'
import { AvailableFeature } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelCorrelationTable } from './FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './FunnelPropertyCorrelationTable'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const {
        isSkewed,
        steps,
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

    if (steps.length <= 1) {
        return null
    }

    return (
        <>
            <h2 className="my-4">Correlation analysis</h2>
            <PayGateMini feature={AvailableFeature.CORRELATION_ANALYSIS}>
                <div className="funnel-correlation">
                    {isSkewed && (
                        <Card className="skew-warning">
                            <h4>
                                <IconFeedbackWarning
                                    style={{ fontSize: 24, marginRight: 4, color: 'var(--warning)' }}
                                />{' '}
                                Adjust your funnel definition to improve correlation analysis
                                <CloseOutlined className="close-button" onClick={hideSkewWarning} />
                            </h4>
                            <div>
                                <b>Tips for adjusting your funnel:</b>
                                <ol>
                                    <li>
                                        Adjust your first funnel step to be more specific. For example, choose a page or
                                        an event that occurs less frequently.
                                    </li>
                                    <li>Choose an event that happens more frequently for subsequent funnels steps.</li>
                                </ol>
                            </div>
                        </Card>
                    )}

                    <FunnelCorrelationTable />

                    {/* Feedback Form */}
                    {!correlationFeedbackHidden && (
                        <div className="border rounded p-4 space-y-2 mt-4">
                            <div className="flex items-center justify-between">
                                <h4 className="text-muted-alt">
                                    <CommentOutlined style={{ marginRight: 4 }} />
                                    Was this correlation analysis report useful?
                                </h4>
                                <div className="flex items-center gap-2">
                                    {!!correlationFeedbackRating && (
                                        <i className="text-success mr-2">Thanks for your feedback!</i>
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
                                        <LemonButton
                                            key={index}
                                            active={correlationFeedbackRating === content[0]}
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
                                        </LemonButton>
                                    ))}
                                    <LemonButton
                                        icon={<IconClose />}
                                        onClick={hideCorrelationAnalysisFeedback}
                                        status="stealth"
                                    />
                                </div>
                            </div>
                            {correlationDetailedFeedbackVisible ? (
                                <>
                                    <form onSubmit={sendCorrelationAnalysisFeedback} className="space-y-2">
                                        <LemonTextArea
                                            onBlur={(e) => setCorrelationDetailedFeedback(e.target.value)}
                                            placeholder="Optional. Help us by sharing details around your experience..."
                                            ref={detailedFeedbackRef}
                                            onPressCmdEnter={() => {
                                                detailedFeedbackRef.current?.blur()
                                                sendCorrelationAnalysisFeedback()
                                            }}
                                        />
                                        <div className="flex justify-end">
                                            <LemonButton
                                                data-attr="correlation-analysis-share-feedback"
                                                type="primary"
                                                htmlType="submit"
                                            >
                                                Share feedback
                                            </LemonButton>
                                        </div>
                                    </form>
                                </>
                            ) : null}
                        </div>
                    )}

                    <FunnelPropertyCorrelationTable />
                </div>
            </PayGateMini>
        </>
    )
}
