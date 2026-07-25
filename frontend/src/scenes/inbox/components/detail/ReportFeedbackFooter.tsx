import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { InboxReportFeedbackSentiment } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'

/**
 * Thumbs rating at the end of the report body, where someone has just finished reading. One click
 * submits, so there's no text field to mistake for the dismissal reason; the row then reads the
 * choice back and stays clickable so a rating can be changed.
 */
export function ReportFeedbackFooter({ report }: { report: SignalReport }): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { feedbackSentiment } = useValues(logic)
    const { rateReport } = useActions(logic)

    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    // Re-clicking the chosen thumb is a no-op rather than a second identical feedback event.
    const rate = (sentiment: InboxReportFeedbackSentiment): void => {
        if (feedbackSentiment !== sentiment) {
            rateReport(sentiment)
        }
    }

    return (
        <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary pt-1 select-none">
            <span>{feedbackSentiment ? 'Thanks for the feedback' : 'Was this report useful?'}</span>
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    type={isPositive ? 'primary' : 'secondary'}
                    icon={isPositive ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    tooltip="Yes, this was useful"
                    aria-label="This report was useful"
                    aria-pressed={isPositive}
                    onClick={() => rate('positive')}
                    data-attr="inbox-report-feedback-thumbs-up"
                />
                <LemonButton
                    size="xsmall"
                    type={isNegative ? 'primary' : 'secondary'}
                    icon={isNegative ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                    tooltip="No, this wasn't useful"
                    aria-label="This report was not useful"
                    aria-pressed={isNegative}
                    onClick={() => rate('negative')}
                    data-attr="inbox-report-feedback-thumbs-down"
                />
            </div>
        </div>
    )
}
