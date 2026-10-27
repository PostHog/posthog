import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { PROVIDER_SETTINGS_URL } from '../../ModelPicker'
import { buildDeliveryTargets, evaluationReportLogic } from '../evaluationReportLogic'
import { runRate } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'
import { reportText } from './evaluationSummary'

/**
 * What the evaluation needs before it can be created, as a checklist, next to what it will do once it runs:
 * how often, at what cost per run, where reports go, and whether it starts running.
 */
export function EvaluationCreateReview({
    checklist,
    onFix,
}: {
    checklist: ChecklistItem[]
    /** Goes to the step that sets an item. */
    onFix: (key: ChecklistKey) => void
}): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const { evaluation, canEnable, canEnableReason, isReportableEvaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const destinations = buildDeliveryTargets(configDraft).length
    const facts = [
        volume ? `Runs ${runRate(volume.runs)}, from last week's traffic.` : null,
        evaluation.evaluation_type === 'llm_judge'
            ? 'Each run is one call to your judge model.'
            : 'Runs make no LLM calls, so they cost nothing extra.',
        configDraft.enabled && isReportableEvaluation
            ? `Reports ${reportText({ ...configDraft, enabled: true })}, ${
                  destinations > 0
                      ? `sent to ${destinations === 1 ? 'one destination' : `${destinations} destinations`}`
                      : 'in the Reports tab'
              }.`
            : 'No reports.',
    ].filter((fact): fact is string => !!fact)

    return (
        <div className="grid grid-cols-1 gap-6 items-start @min-[40rem]/evaluation:grid-cols-2">
            <ul className="flex flex-col gap-2 m-0 p-0 list-none" data-attr="llma-evaluation-create-checklist">
                {checklist.map((item) => (
                    <li key={item.key} className="flex items-start gap-2 text-sm">
                        {item.done ? (
                            <IconCheckCircle className="text-success text-base shrink-0 mt-0.5" />
                        ) : (
                            <IconCircleDashed className="text-secondary text-base shrink-0 mt-0.5" />
                        )}
                        <span className="flex flex-col min-w-0">
                            <span className={cn(item.done ? 'text-secondary' : 'font-semibold')}>{item.label}</span>
                            {!item.done &&
                                (item.fixInSettings ? (
                                    <Link
                                        to={PROVIDER_SETTINGS_URL}
                                        target="_blank"
                                        data-attr="llma-evaluation-create-add-key"
                                    >
                                        {item.todo}
                                    </Link>
                                ) : (
                                    <Link onClick={() => onFix(item.key)}>{item.todo}</Link>
                                ))}
                        </span>
                    </li>
                ))}
            </ul>
            <div
                className="border rounded p-4 bg-surface-primary flex flex-col gap-3"
                data-attr="llma-evaluation-create-glance"
            >
                <h4 className="mb-0 text-sm font-semibold">At a glance</h4>
                <ul className="m-0 pl-4 flex flex-col gap-1 text-sm">
                    {facts.map((fact) => (
                        <li key={fact}>{fact}</li>
                    ))}
                </ul>
                <LemonSwitch
                    checked={evaluation.enabled}
                    onChange={setEvaluationEnabled}
                    disabledReason={!canEnable && !evaluation.enabled ? (canEnableReason ?? undefined) : undefined}
                    label="Start running when created"
                    bordered
                    fullWidth
                    data-attr="llma-evaluation-create-enabled"
                />
                <span className="text-xs text-secondary -mt-2">
                    {evaluation.enabled
                        ? 'It checks new matching traffic as soon as you create it.'
                        : 'It stays paused. Turn it on from its page when you are ready.'}
                </span>
            </div>
        </div>
    )
}
