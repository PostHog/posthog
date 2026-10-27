import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { ReportFormFields } from '../components/EvaluationReportConfig'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** Scheduled reports, with the same settings as on the evaluation's page. */
export function EvaluationReportsPanel(): JSX.Element | null {
    const { evaluation, isReportableEvaluation } = useValues(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: 'new' }))
    const { setDraftEnabled } = useActions(evaluationReportLogic({ evaluationId: 'new' }))

    if (!evaluation) {
        return null
    }
    // Reports read pass rates, so a score or category evaluation needs its passing rule first.
    const unavailableReason = isReportableEvaluation
        ? null
        : evaluation.output_type === 'numeric'
          ? 'Set a passing score under Return to get reports.'
          : evaluation.output_type === 'categorical'
            ? 'Mark a category as a pass under Return to get reports.'
            : 'Reports are not available for this kind of evaluation.'
    const enabled = configDraft.enabled && !unavailableReason

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="mb-0 text-sm text-secondary">
                    An agent reads the results and writes up what changed, with examples.
                </p>
                <LemonSwitch
                    checked={enabled}
                    onChange={setDraftEnabled}
                    disabledReason={unavailableReason ?? undefined}
                    bordered
                    label={enabled ? 'Enabled' : 'Disabled'}
                    data-attr="llma-evaluation-create-reports-switch"
                />
            </div>
            {unavailableReason ? (
                <p className="mb-0 text-sm text-secondary">{unavailableReason}</p>
            ) : (
                enabled && <ReportFormFields evaluationId="new" />
            )}
        </div>
    )
}
