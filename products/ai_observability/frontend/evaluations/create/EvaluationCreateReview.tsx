import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconClock, IconNotification, IconSparkles } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { capitalizeFirstLetter } from 'lib/utils/strings'

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
    const { evaluation, canEnable, canEnableReason, isReportableEvaluation, selectedModel, selectedModelName } =
        useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))

    if (!evaluation) {
        return null
    }
    const destinations = buildDeliveryTargets(configDraft).length
    const reportsOn = configDraft.enabled && isReportableEvaluation
    const facts: { key: string; icon: JSX.Element; title: string; detail: string }[] = [
        ...(volume
            ? [
                  {
                      key: 'volume',
                      icon: <IconClock />,
                      title: capitalizeFirstLetter(runRate(volume.runs)),
                      detail: "From last week's matching traffic",
                  },
              ]
            : []),
        {
            key: 'judge',
            icon: <IconSparkles />,
            title:
                evaluation.evaluation_type === 'llm_judge'
                    ? `Judged by ${selectedModelName ?? (selectedModel || 'the model you pick')}`
                    : 'No AI key needed',
            detail:
                evaluation.evaluation_type === 'llm_judge'
                    ? 'Uses your own AI provider key'
                    : evaluation.evaluation_type === 'hog'
                      ? 'Your code decides each result'
                      : 'A built-in classifier decides each result',
        },
        {
            key: 'reports',
            icon: <IconNotification />,
            title: reportsOn
                ? `${capitalizeFirstLetter(reportText({ ...configDraft, enabled: true }))} reports`
                : 'No reports',
            detail: reportsOn
                ? destinations > 0
                    ? `Sent to ${destinations === 1 ? 'one destination' : `${destinations} destinations`}`
                    : 'In the Reports tab'
                : 'Turn them on in the Reports step',
        },
    ]
    const done = checklist.filter((item) => item.done).length

    return (
        <div className="grid grid-cols-1 gap-4 @min-[40rem]/evaluation:grid-cols-2">
            <div className="border rounded p-4 flex flex-col gap-3">
                <div className="flex items-center justify-between gap-2">
                    <h4 className="mb-0 text-sm font-semibold">Checklist</h4>
                    <span className="text-xs text-secondary">{`${done} of ${checklist.length} done`}</span>
                </div>
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
            </div>
            <div className="border rounded p-4 flex flex-col gap-3" data-attr="llma-evaluation-create-glance">
                <h4 className="mb-0 text-sm font-semibold">At a glance</h4>
                <ul className="m-0 p-0 list-none flex flex-col gap-3">
                    {facts.map((fact) => (
                        <li key={fact.key} className="flex items-start gap-3">
                            <span className="flex size-8 shrink-0 items-center justify-center rounded bg-fill-highlight-100 text-lg text-secondary">
                                {fact.icon}
                            </span>
                            <span className="flex flex-col min-w-0">
                                <span className="text-sm font-semibold">{fact.title}</span>
                                <span className="text-xs text-secondary">{fact.detail}</span>
                            </span>
                        </li>
                    ))}
                </ul>
                <div className="mt-auto flex flex-col gap-1 pt-2">
                    <LemonSwitch
                        checked={evaluation.enabled}
                        onChange={setEvaluationEnabled}
                        disabledReason={!canEnable && !evaluation.enabled ? (canEnableReason ?? undefined) : undefined}
                        label="Start running when created"
                        bordered
                        fullWidth
                        data-attr="llma-evaluation-create-enabled"
                    />
                    <span className="text-xs text-secondary">
                        {evaluation.enabled
                            ? 'It checks new matching traffic as soon as you create it.'
                            : 'It stays paused. Turn it on from its page when you are ready.'}
                    </span>
                </div>
            </div>
        </div>
    )
}
