import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'
import { DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsDataLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

const MIN_STEPS = 2

export function PathStepPickerNext(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

    const { stepLimit } = pathsFilter || {}

    const maxSteps = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) ? 20 : 5
    const options = Array.from({ length: maxSteps - MIN_STEPS + 1 }, (_, index) => {
        const steps = MIN_STEPS + index
        return { value: String(steps), label: `${steps} Steps` }
    })
    const items = Object.fromEntries(options.map((option) => [option.value, option.label]))

    return (
        <Select
            value={String(stepLimit || DEFAULT_STEP_LIMIT)}
            items={items}
            onValueChange={(value: string | null) => {
                if (value) {
                    updateInsightFilter({ stepLimit: parseInt(value) })
                }
            }}
            disabled={!!editingDisabledReason}
        >
            <SelectTrigger size="sm" data-quill data-attr="path-step-filter" title={editingDisabledReason ?? undefined}>
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
