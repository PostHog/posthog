import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
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
    const { insightProps } = useValues(insightLogic)
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { step_limit } = pathsFilter || {}

    const { user } = useValues(userLogic)

    const MIN = 2,
        MAX = user?.organization?.available_features.includes(AvailableFeature.PATHS_ADVANCED) ? 20 : 5

    const options: StepOption[] = Array.from(Array.from(Array.from(Array(MAX + 1).keys()).slice(MIN)), (v) => ({
        label: `${v} Steps`,
        value: v,
    }))

    return (
        <LemonSelect
            size="small"
            value={step_limit || DEFAULT_STEP_LIMIT}
            onChange={(count) => updateInsightFilter({ step_limit: count })}
            options={options}
        />
    )
}
