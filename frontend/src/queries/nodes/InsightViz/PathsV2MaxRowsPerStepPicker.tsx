import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { pathsV2DataLogic } from 'scenes/paths-v2/pathsV2DataLogic'

import { insightLogic } from '../../../scenes/insights/insightLogic'

// Keep in sync with defaults in schema
const DEFAULT_MAX_ROWS_PER_STEP = 3

const MAX_ROWS_PER_STEP_MINIMUM = 2
const MAX_ROWS_PER_STEP_MAXIMUM = 20

export function PathsV2MaxRowsPerStepPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { pathsV2Filter } = useValues(pathsV2DataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsV2DataLogic(insightProps))

    const { maxRowsPerStep } = pathsV2Filter || {}

    const options = Array.from(
        Array.from(Array.from(Array(MAX_ROWS_PER_STEP_MAXIMUM + 1).keys()).slice(MAX_ROWS_PER_STEP_MINIMUM)),
        (v) => ({
            label: `${v} Rows`,
            value: v,
        })
    )

    return (
        <LemonSelect
            size="small"
            value={maxRowsPerStep || DEFAULT_MAX_ROWS_PER_STEP}
            onChange={(count) => updateInsightFilter({ maxRowsPerStep: count })}
            options={options}
        />
    )
}
