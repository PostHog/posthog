import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { evaluationReportLogic } from '../evaluationReportLogic'

interface EvaluationReportsCalloutProps {
    evaluationId: string
    /** Opens the schedule form, which lives in the Configuration tab. */
    onSetUpClick: () => void
}

export function EvaluationReportsCallout({
    evaluationId,
    onSetUpClick,
}: EvaluationReportsCalloutProps): JSX.Element | null {
    const { activeReport, reportsLoading } = useValues(evaluationReportLogic({ evaluationId }))

    // Hold the banner back until the schedule has resolved, so anyone who already has one never
    // sees it flash.
    if (reportsLoading || activeReport) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mb-4"
            // pinned: localStorage key - renaming it un-dismisses the banner for everyone
            dismissKey="llma-evaluation-reports-callout"
            action={{
                children: 'Set up reports',
                onClick: onSetUpClick,
                'data-attr': 'llma-evaluation-reports-callout-cta',
            }}
        >
            Scheduled reports analyze these runs for you and send the results to email or Slack, daily, weekly, or every
            N evaluations.
        </LemonBanner>
    )
}
