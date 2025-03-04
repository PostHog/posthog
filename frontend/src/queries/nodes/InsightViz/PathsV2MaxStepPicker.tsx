import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { pathsV2DataLogic } from 'scenes/paths-v2/pathsV2DataLogic'

import { insightLogic } from '../../../scenes/insights/insightLogic'

// Keep in sync with defaults in schema
const DEFAULT_MAX_STEPS = 5

const MAX_STEPS_MINIMUM = 2
const MAX_STEPS_MAXIMUM = 20

export function PathsV2MaxStepPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { pathsV2Filter } = useValues(pathsV2DataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsV2DataLogic(insightProps))

    const { maxSteps } = pathsV2Filter || {}

    const options = Array.from(
        Array.from(Array.from(Array(MAX_STEPS_MAXIMUM + 1).keys()).slice(MAX_STEPS_MINIMUM)),
        (v) => ({
            label: `${v} Steps`,
            value: v,
        })
    )

    return (
        <LemonSelect
            size="small"
            value={maxSteps || DEFAULT_MAX_STEPS}
            onChange={(count) => updateInsightFilter({ maxSteps: count })}
            options={options}
        />
    )
}
