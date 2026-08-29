import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { evaluationReportLogic } from '../evaluationReportLogic'

interface EvaluationReportsCalloutProps {
    evaluationId: string
    onReportsClick: () => void
}

export function EvaluationReportsCallout({
    evaluationId,
    onReportsClick,
}: EvaluationReportsCalloutProps): JSX.Element | null {
    const { activeReport, reportsLoading } = useValues(evaluationReportLogic({ evaluationId }))

    // Hold the banner back until the schedule has resolved so anyone with enabled reports never sees it flash.
    if (reportsLoading || activeReport?.enabled) {
        return null
    }

    return (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="text-muted">
                Evaluation reports analyze these runs and send results by email or Slack.
            </span>
            <LemonButton
                type="secondary"
                size="xsmall"
                onClick={onReportsClick}
                data-attr="llma-evaluation-reports-callout-cta"
            >
                Go to reports
            </LemonButton>
        </div>
    )
}
