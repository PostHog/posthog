import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { PROVIDER_SETTINGS_URL } from '../../ModelPicker'
import { buildDeliveryTargets, evaluationReportLogic } from '../evaluationReportLogic'
import { runRate } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'
import { methodText, reportText, returnText, targetText, triggerText } from './evaluationSummary'

export interface ReviewRow {
    key: string
    title: string
    /** The checklist items this row's step completes. */
    checks: ChecklistKey[]
    onEdit: () => void
}

/** Each step's choices in one line, with what is still missing, so the evaluation can be checked before creating it. */
export function EvaluationCreateReview({
    rows,
    checklist,
}: {
    rows: ReviewRow[]
    checklist: ChecklistItem[]
}): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const {
        evaluation,
        usesDecisionModel,
        selectedModelName,
        selectedModel,
        isReportableEvaluation,
        canEnable,
        canEnableReason,
    } = useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const reportsOn = configDraft.enabled && isReportableEvaluation
    const destinations = buildDeliveryTargets(configDraft).length
    const summaries: Record<string, string> = {
        name: evaluation.name.trim() || 'No name yet',
        check: `${methodText(evaluation, usesDecisionModel, selectedModelName ?? (selectedModel || undefined))}${
            evaluation.evaluation_type === 'sentiment' ? '' : `, returns ${returnText(evaluation)}`
        }`,
        traffic: `${targetText(evaluation)}, ${triggerText(evaluation)}${volume ? `, ${runRate(volume.runs)}` : ''}`,
        reports: reportsOn
            ? `${reportText({ ...configDraft, enabled: true })}, ${
                  destinations > 0
                      ? `sent to ${destinations === 1 ? 'one destination' : `${destinations} destinations`}`
                      : 'in the Reports tab'
              }`
            : 'Off',
    }

    return (
        <div className="flex flex-col gap-4">
            <ul className="m-0 p-0 list-none border rounded divide-y" data-attr="llma-evaluation-create-checklist">
                {rows.map((row) => {
                    const missing = checklist.filter((item) => row.checks.includes(item.key) && !item.done)
                    return (
                        <li key={row.key} className="flex items-start gap-3 px-4 py-3">
                            {missing.length > 0 ? (
                                <IconWarning className="text-danger text-lg shrink-0 mt-0.5" />
                            ) : (
                                <IconCheckCircle className="text-success text-lg shrink-0 mt-0.5" />
                            )}
                            <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                                <span className="text-xs font-semibold text-secondary">{row.title}</span>
                                <span className="text-sm truncate">{capitalizeFirstLetter(summaries[row.key])}</span>
                                {missing.map((item) =>
                                    item.fixInSettings ? (
                                        <Link
                                            key={item.key}
                                            to={PROVIDER_SETTINGS_URL}
                                            target="_blank"
                                            className="text-sm"
                                            data-attr="llma-evaluation-create-add-key"
                                        >
                                            {item.todo}
                                        </Link>
                                    ) : (
                                        <span key={item.key} className="text-sm text-danger">
                                            {item.todo}
                                        </span>
                                    )
                                )}
                            </div>
                            <LemonButton
                                size="small"
                                type="tertiary"
                                onClick={row.onEdit}
                                data-attr={`llma-evaluation-create-review-edit-${row.key}`}
                            >
                                Edit
                            </LemonButton>
                        </li>
                    )
                })}
            </ul>
            <div className="flex flex-col gap-1">
                <LemonSwitch
                    checked={evaluation.enabled}
                    onChange={setEvaluationEnabled}
                    disabledReason={!canEnable && !evaluation.enabled ? (canEnableReason ?? undefined) : undefined}
                    label="Start running when created"
                    bordered
                    data-attr="llma-evaluation-create-enabled"
                />
                <span className="text-xs text-secondary">
                    {evaluation.enabled
                        ? 'It checks new matching traffic as soon as you create it.'
                        : 'It stays paused. Turn it on from its page when you are ready.'}
                </span>
            </div>
        </div>
    )
}
