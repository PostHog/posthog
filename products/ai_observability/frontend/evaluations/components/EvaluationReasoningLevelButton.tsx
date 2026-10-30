import { useActions, useValues } from 'kea'

import { IconBrain } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ReasoningLevel } from '../types'

const REASONING_LEVEL_OPTIONS: { value: ReasoningLevel | null; label: string }[] = [
    { value: null, label: 'Model default' },
    { value: 'minimal', label: 'Minimal' },
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
]

export function EvaluationReasoningLevelButton(): JSX.Element {
    const { reasoningLevel } = useValues(llmEvaluationLogic)
    const { setReasoningLevel } = useActions(llmEvaluationLogic)

    return (
        <LemonMenu
            placement="bottom-end"
            items={REASONING_LEVEL_OPTIONS.map(({ value, label }) => ({
                label,
                active: value === reasoningLevel,
                onClick: () => setReasoningLevel(value),
            }))}
        >
            <LemonButton
                type="secondary"
                icon={<IconBrain />}
                tooltip="Reasoning effort. Higher levels can judge harder cases better, but cost more and take longer."
                aria-label="Reasoning effort"
                data-attr="evaluation-reasoning-level"
            >
                {reasoningLevel && REASONING_LEVEL_OPTIONS.find((option) => option.value === reasoningLevel)?.label}
            </LemonButton>
        </LemonMenu>
    )
}
