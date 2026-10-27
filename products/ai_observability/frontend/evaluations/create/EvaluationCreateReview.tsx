import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { PROVIDER_SETTINGS_URL } from '../../ModelPicker'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'

/** What the evaluation needs before it can be created, as a checklist, and whether it starts running. */
export function EvaluationCreateReview({
    checklist,
    onFix,
}: {
    checklist: ChecklistItem[]
    /** Goes to the step that sets an item. */
    onFix: (key: ChecklistKey) => void
}): JSX.Element | null {
    const { evaluation, canEnable, canEnableReason } = useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    return (
        <div className="flex flex-col gap-4">
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
