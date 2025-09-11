import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { IconComment } from 'lib/lemon-ui/icons'
import { funnelCorrelationFeedbackLogic } from 'scenes/funnels/funnelCorrelationFeedbackLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export const FunnelCorrelationFeedbackForm = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { correlationFeedbackHidden, correlationDetailedFeedbackVisible, correlationFeedbackRating } = useValues(
        funnelCorrelationFeedbackLogic(insightProps)
    )
    const {
        sendCorrelationAnalysisFeedback,
        hideCorrelationAnalysisFeedback,
        setCorrelationFeedbackRating,
        setCorrelationDetailedFeedback,
    } = useActions(funnelCorrelationFeedbackLogic(insightProps))

    const detailedFeedbackRef = useRef<HTMLTextAreaElement>(null)

    if (correlationFeedbackHidden) {
        return null
    }

    return (
        <div className="border rounded p-4 deprecated-space-y-2 mt-4">
            <div className="flex items-center justify-between">
                <h4 className="text-secondary">
                    <IconComment style={{ marginRight: 4 }} />
                    Was this correlation analysis report useful?
                </h4>
                <div className="flex items-center gap-2">
                    {!!correlationFeedbackRating && <i className="text-success mr-2">Thanks for your feedback!</i>}
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
                    <LemonButton icon={<IconX />} onClick={hideCorrelationAnalysisFeedback} />
                </div>
            </div>
            {correlationDetailedFeedbackVisible ? (
                <>
                    <form onSubmit={sendCorrelationAnalysisFeedback} className="deprecated-space-y-2">
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
    )
}
