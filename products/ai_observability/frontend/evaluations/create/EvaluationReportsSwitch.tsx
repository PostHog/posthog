import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { reportsUnavailableReason } from './evaluationSummary'

/** Turns scheduled reports on or off, and says why it cannot while the evaluation has no pass rate. */
export function EvaluationReportsSwitch(): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const { evaluation, isReportableEvaluation } = useValues(llmEvaluationLogic)
    const { configDraft, reportsLoading, activeReport } = useValues(
        evaluationReportLogic({ evaluationId: props.evaluationId })
    )
    const { setDraftEnabled } = useActions(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const unavailableReason = reportsUnavailableReason(evaluation, isReportableEvaluation)
    const enabled = configDraft.enabled && !unavailableReason
    return (
        <LemonSwitch
            checked={enabled}
            onChange={setDraftEnabled}
            // Loading the saved settings replaces the draft, so a toggle before then would be lost.
            disabledReason={
                unavailableReason ??
                (props.evaluationId !== 'new' && reportsLoading && !activeReport
                    ? 'Loading the saved report settings'
                    : undefined)
            }
            bordered
            label={enabled ? 'Enabled' : 'Disabled'}
            data-attr="llma-evaluation-create-reports-switch"
        />
    )
}
