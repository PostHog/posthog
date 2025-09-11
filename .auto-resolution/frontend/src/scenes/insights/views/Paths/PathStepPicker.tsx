import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsDataLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

interface StepOption {
    label: string
    value: number
}

export function PathStepPicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

    const { stepLimit } = pathsFilter || {}

    const MIN = 2,
        MAX = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) ? 20 : 5

    const options: StepOption[] = Array.from(Array.from(Array.from(Array(MAX + 1).keys()).slice(MIN)), (v) => ({
        label: `${v} Steps`,
        value: v,
    }))

    return (
        <LemonSelect
            size="small"
            value={stepLimit || DEFAULT_STEP_LIMIT}
            onChange={(count) => updateInsightFilter({ stepLimit: count })}
            options={options}
            disabledReason={editingDisabledReason}
        />
    )
}
