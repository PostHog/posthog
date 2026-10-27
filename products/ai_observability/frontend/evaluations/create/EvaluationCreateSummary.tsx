import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { PROVIDER_SETTINGS_URL } from '../../ModelPicker'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem } from './creationChecklist'
import { EvaluationCreateButton } from './EvaluationCreateButton'
import { summarySentence } from './evaluationSummary'

/** What is left before the evaluation can be created, what it will run on, and the create action. */
export function EvaluationCreateSummary({
    checklist,
    onCreate,
    onCancel,
}: {
    checklist: ChecklistItem[]
    onCreate: () => void
    onCancel: () => void
}): JSX.Element | null {
    const { evaluation, canEnable, canEnableReason, usesDecisionModel, selectedModel, selectedModelName } =
        useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)

    if (!evaluation) {
        return null
    }
    const firstTodo = checklist.find((item) => !item.done)
    const shown = checklist.filter((item) => !(item.done && item.hiddenWhenDone))
    const sentence = summarySentence({
        evaluation,
        usesDecisionModel,
        modelName: selectedModelName ?? (selectedModel || undefined),
        runs: volume?.runs ?? null,
    })

    return (
        <aside className="bg-bg-light border rounded p-4 flex flex-col gap-4">
            <h3 className="mb-0 text-base font-semibold">{firstTodo ? 'Before you create' : 'Ready to create'}</h3>
            {/* The checklist only matters while something is left. After that, one sentence says what will run. */}
            {firstTodo && (
                <ul className="flex flex-col gap-2 m-0 p-0 list-none" data-attr="llma-evaluation-create-checklist">
                    {shown.map((item) => (
                        <li key={item.key} className="flex items-start gap-2 text-sm">
                            {item.done ? (
                                <IconCheckCircle className="text-success text-base shrink-0 mt-0.5" />
                            ) : (
                                <IconCircleDashed className="text-secondary text-base shrink-0 mt-0.5" />
                            )}
                            <span className="flex flex-col min-w-0">
                                <span className={cn(item.done ? 'text-secondary' : 'font-semibold')}>{item.label}</span>
                                {!item.done && item.todo && <span className="text-secondary">{item.todo}</span>}
                                {!item.done && item.fixInSettings && (
                                    <Link
                                        to={PROVIDER_SETTINGS_URL}
                                        target="_blank"
                                        data-attr="llma-evaluation-create-add-key"
                                    >
                                        Add a provider key
                                    </Link>
                                )}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
            <p className="mb-0 text-sm text-secondary" data-attr="llma-evaluation-create-scope">
                {sentence}
            </p>
            <div className="flex flex-col gap-1">
                <LemonSwitch
                    checked={evaluation.enabled}
                    onChange={setEvaluationEnabled}
                    disabledReason={!canEnable && !evaluation.enabled ? (canEnableReason ?? undefined) : undefined}
                    label="Start running when created"
                    bordered
                    fullWidth
                    data-attr="llma-evaluation-create-enabled"
                />
                {!evaluation.enabled && canEnable && (
                    <span className="text-xs text-secondary">Turn it on from its page when you are ready.</span>
                )}
            </div>
            <div className="flex flex-col gap-2">
                <EvaluationCreateButton
                    onCreate={onCreate}
                    disabledReason={firstTodo?.todo}
                    fullWidth
                    data-attr="llma-evaluation-create-submit"
                />
                <LemonButton type="tertiary" center fullWidth onClick={onCancel}>
                    Cancel
                </LemonButton>
            </div>
        </aside>
    )
}
