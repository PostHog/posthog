import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { ReportFormFields } from '../components/EvaluationReportConfig'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { CreateStep, type StepProgress } from './CreateStep'

/** Step four: scheduled reports, with the same settings as on the evaluation's page. */
export function EvaluationReportsStep(progress: StepProgress): JSX.Element | null {
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
          ? 'Set a passing score in step 2 to get reports.'
          : evaluation.output_type === 'categorical'
            ? 'Mark a category as a pass in step 2 to get reports.'
            : 'Reports are not available for this kind of evaluation.'
    const enabled = configDraft.enabled && !unavailableReason

    return (
        <CreateStep
            number={4}
            title="Scheduled reports"
            summary={enabled ? 'On' : 'Off'}
            {...progress}
            description="An agent reads the results and writes up what changed, with examples."
            action={
                <LemonSwitch
                    checked={enabled}
                    onChange={setDraftEnabled}
                    disabledReason={unavailableReason ?? undefined}
                    bordered
                    label={enabled ? 'Enabled' : 'Disabled'}
                    data-attr="llma-evaluation-create-reports-switch"
                />
            }
        >
            {unavailableReason ? (
                <p className="mb-0 text-sm text-secondary">{unavailableReason}</p>
            ) : (
                enabled && <ReportFormFields evaluationId="new" />
            )}
        </CreateStep>
    )
}
