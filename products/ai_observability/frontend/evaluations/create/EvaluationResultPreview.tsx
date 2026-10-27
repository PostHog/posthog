import { useActions, useValues } from 'kea'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import { IconCircleDashed } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { PROVIDER_SETTINGS_URL } from '../../ModelPicker'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { runRate } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationConfig } from '../types'
import type { ChecklistItem } from './creationChecklist'
import { EvaluationCreateButton } from './EvaluationCreateButton'
import { reportText, returnText } from './evaluationSummary'

const HogJudge = pngHoggie(judgePng)

// Bar heights for the placeholder chart. They only suggest a chart and carry no data.
const PLACEHOLDER_BARS = [35, 50, 42, 60, 55, 68, 58, 72, 64, 78, 70, 82]

/** The numbers the evaluation's page will show for this kind of result. */
function resultMetric(evaluation: EvaluationConfig): string {
    const hasRule = !!evaluation.output_config.passing_rule
    switch (evaluation.output_type) {
        case 'numeric':
            return hasRule ? 'Pass rate and average score' : 'Average score'
        case 'categorical':
            return hasRule ? 'Pass rate and how often each category comes up' : 'How often each category comes up'
        case 'sentiment':
            return 'How often each sentiment comes up'
        default:
            return 'Pass rate'
    }
}

/** What the evaluation will produce, what is left before it can be created, and the create action. */
export function EvaluationResultPreview({
    checklist,
    onCreate,
    onCancel,
}: {
    checklist: ChecklistItem[]
    onCreate: () => void
    onCancel: () => void
}): JSX.Element | null {
    const { evaluation, canEnable, canEnableReason, isReportableEvaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: 'new' }))

    if (!evaluation) {
        return null
    }
    const todo = checklist.filter((item) => !item.done)
    const reports = reportText({ ...configDraft, enabled: configDraft.enabled && isReportableEvaluation })

    return (
        <aside className="bg-bg-light border rounded p-4 flex flex-col gap-4">
            <div className="flex items-center gap-3">
                <HogJudge className="w-14 shrink-0" />
                <div className="flex flex-col min-w-0">
                    <h3 className="mb-0 text-base font-semibold">What you'll get</h3>
                    <span className="text-xs text-secondary">Results show here after the first run.</span>
                </div>
            </div>
            <div className="border rounded p-3 flex flex-col gap-3" data-attr="llma-evaluation-create-preview">
                <div className="flex flex-col min-w-0">
                    <span className="font-semibold truncate">{evaluation.name.trim() || 'Untitled evaluation'}</span>
                    <span className="text-xs text-secondary">Returns {returnText(evaluation)}</span>
                </div>
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-secondary">{resultMetric(evaluation)}, over time</span>
                    <div className="flex items-end gap-0.5 h-8" aria-hidden>
                        {PLACEHOLDER_BARS.map((height, index) => (
                            <div
                                key={index}
                                className="flex-1 rounded-sm bg-fill-highlight-100"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: `${height}%` }}
                            />
                        ))}
                    </div>
                </div>
                <ul className="m-0 p-0 list-none flex flex-col gap-1 text-sm" data-attr="llma-evaluation-create-scope">
                    {volume && <li>{`Runs ${runRate(volume.runs)}, from last week's traffic`}</li>}
                    <li>{reports.charAt(0).toUpperCase() + reports.slice(1)}</li>
                </ul>
            </div>
            {todo.length > 0 && (
                <ul className="flex flex-col gap-2 m-0 p-0 list-none" data-attr="llma-evaluation-create-checklist">
                    {todo.map((item) => (
                        <li key={item.key} className="flex items-start gap-2 text-sm">
                            <IconCircleDashed className="text-secondary text-base shrink-0 mt-0.5" />
                            <span className="flex flex-col min-w-0">
                                <span className="font-semibold">{item.label}</span>
                                {item.todo && <span className="text-secondary">{item.todo}</span>}
                                {item.fixInSettings && (
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
                    disabledReason={todo[0]?.todo}
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
