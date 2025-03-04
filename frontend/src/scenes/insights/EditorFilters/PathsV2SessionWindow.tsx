import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { pathsV2DataLogic } from 'scenes/paths-v2/pathsV2DataLogic'

import { ConversionWindowIntervalUnit, EditorFilterProps } from '~/types'

const TIME_INTERVAL_BOUNDS: Record<ConversionWindowIntervalUnit, number[]> = {
    [ConversionWindowIntervalUnit.Second]: [1, 3600],
    [ConversionWindowIntervalUnit.Minute]: [1, 1440],
    [ConversionWindowIntervalUnit.Hour]: [1, 24],
    [ConversionWindowIntervalUnit.Day]: [1, 365],
    [ConversionWindowIntervalUnit.Week]: [1, 53],
    [ConversionWindowIntervalUnit.Month]: [1, 12],
}

// Keep in sync with defaults in schema
const DEFAULT_WINDOW_INTERVAL = 14
const DEFAULT_WINDOW_INTERVAL_UNIT = ConversionWindowIntervalUnit.Day

// TODO: Extract a generic converion window component
// Forked from https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/insights/views/Funnels/FunnelConversionWindowFilter.tsx
function ConversionWindowFilter({
    windowInterval = DEFAULT_WINDOW_INTERVAL,
    windowIntervalUnit = DEFAULT_WINDOW_INTERVAL_UNIT,
    onWindowIntervalChange,
    onWindowIntervalUnitChange,
}: {
    windowInterval: number | undefined
    windowIntervalUnit: ConversionWindowIntervalUnit | undefined
    onWindowIntervalChange: (windowInterval: number | undefined) => void
    onWindowIntervalUnitChange: (windowIntervalUnit: ConversionWindowIntervalUnit) => void
}): JSX.Element {
    const options: LemonSelectOption<ConversionWindowIntervalUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(windowInterval ?? 7, unit, `${unit}s`, false)),
            value: unit as ConversionWindowIntervalUnit,
        })
    )
    const intervalBounds = TIME_INTERVAL_BOUNDS[windowIntervalUnit ?? ConversionWindowIntervalUnit.Day]

    return (
        <div className="flex items-center gap-2">
            <span className="flex whitespace-nowrap">
                Conversion window limit
                <Tooltip title={<>Split events in date range into sessions.</>}>
                    <IconInfo className="w-4 info-indicator" />
                </Tooltip>
            </span>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="number"
                    className="max-w-20"
                    fullWidth={false}
                    min={intervalBounds[0]}
                    max={intervalBounds[1]}
                    value={windowInterval}
                    onChange={onWindowIntervalChange}
                />
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    value={windowIntervalUnit}
                    onChange={onWindowIntervalUnitChange}
                    options={options}
                />
            </div>
        </div>
    )
}

export function PathsV2SessionWindow({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsV2DataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsV2DataLogic(insightProps))

    return <ConversionWindowFilter />
}
