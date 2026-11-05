import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { VOLUME_LOOKBACK_DAYS } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'

/** What the evaluation needs before it can be created, next to what happens once it is created. */
export function EvaluationCreateReview({
    checklist,
    onFix,
}: {
    checklist: ChecklistItem[]
    /** Goes to the step that sets an item. */
    onFix: (key: ChecklistKey) => void
}): JSX.Element | null {
    const { evaluation, canEnableReason, checkPastTraffic } = useValues(llmEvaluationLogic)
    const { setCheckPastTraffic } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)

    if (!evaluation) {
        return null
    }
    // Unknown volume (still counting, or a filter on content) still offers it; only a known zero hides it.
    const hasPastTraffic = volume?.runs !== 0
    const units = volume ? pluralize(volume.matchingUnits, volume.target) : null
    // Below 100% sampling the exact count depends on which units the sample picks, so it names the pool instead.
    const pastTrafficCount = !volume
        ? ''
        : volume.runs === volume.matchingUnits
          ? ` It will evaluate ${units}.`
          : ` It will evaluate a sample of the ${units} that matched.`
    const pastTrafficDetail = `See results right away instead of waiting for new traffic.${pastTrafficCount}${
        evaluation.evaluation_type === 'llm_judge' ? ' Each one will be a call to your judge model.' : ''
    }`
    const done = checklist.filter((item) => item.done).length

    return (
        <div className="flex flex-col gap-3 w-full max-w-xl mx-auto">
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
                                {item.done && item.summary && (
                                    <span className="text-xs text-secondary truncate">{item.summary}</span>
                                )}
                                {!item.done && <Link onClick={() => onFix(item.key)}>{item.todo}</Link>}
                            </span>
                        </li>
                    ))}
                </ul>
            </div>
            {evaluation.enabled && hasPastTraffic && (
                <div className="border rounded px-4 py-3 flex flex-col gap-1">
                    <LemonCheckbox
                        checked={checkPastTraffic}
                        onChange={setCheckPastTraffic}
                        label={`Also evaluate the last ${VOLUME_LOOKBACK_DAYS} days`}
                        data-attr="llma-evaluation-create-past-traffic"
                    />
                    <span className="text-xs text-secondary pl-6">{pastTrafficDetail}</span>
                </div>
            )}
            {!evaluation.enabled && (
                <p className="mb-0 text-sm text-secondary">
                    {`It is created paused. ${canEnableReason ?? ''} Then turn it on from its page.`}
                </p>
            )}
        </div>
    )
}
