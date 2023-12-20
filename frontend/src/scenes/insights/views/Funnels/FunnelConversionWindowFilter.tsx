import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { useState } from 'react'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { useDebouncedCallback } from 'use-debounce'

import { FunnelsFilter } from '~/queries/schema'
import { EditorFilterProps, FunnelConversionWindow, FunnelConversionWindowTimeUnit } from '~/types'

const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
    [FunnelConversionWindowTimeUnit.Second]: [1, 3600],
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

export function FunnelConversionWindowFilter({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { insightFilter, querySource } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnel_window_interval = 14, funnel_window_interval_unit = FunnelConversionWindowTimeUnit.Day } =
        (insightFilter || {}) as FunnelsFilter

    const [localConversionWindow, setLocalConversionWindow] = useState<FunnelConversionWindow>({
        funnel_window_interval,
        funnel_window_interval_unit,
    })

    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(funnel_window_interval ?? 7, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )
    const intervalBounds = TIME_INTERVAL_BOUNDS[funnel_window_interval_unit ?? FunnelConversionWindowTimeUnit.Day]

    const setConversionWindow = useDebouncedCallback((): void => {
        if (
            localConversionWindow.funnel_window_interval !== funnel_window_interval ||
            localConversionWindow.funnel_window_interval_unit !== funnel_window_interval_unit
        ) {
            updateInsightFilter(localConversionWindow)
        }
    }, 200)

    return (
        <div className="flex items-center gap-2">
            <span className="flex whitespace-nowrap">
                Conversion window limit
                <Tooltip
                    title={
                        <>
                            <b>Recommended!</b> Limit to {aggregationTargetLabel.plural}{' '}
                            {querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'} converted within a
                            specific time frame. {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                            {querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'} do not convert in
                            this time frame will be considered as drop-offs.
                        </>
                    }
                >
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
                    defaultValue={funnel_window_interval}
                    value={localConversionWindow.funnel_window_interval}
                    onChange={(funnel_window_interval) => {
                        setLocalConversionWindow((state) => ({
                            ...state,
                            funnel_window_interval: Number(funnel_window_interval),
                        }))
                        setConversionWindow()
                    }}
                    onBlur={setConversionWindow}
                    onPressEnter={setConversionWindow}
                />
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    value={localConversionWindow.funnel_window_interval_unit}
                    onChange={(funnel_window_interval_unit: FunnelConversionWindowTimeUnit | null) => {
                        if (funnel_window_interval_unit) {
                            setLocalConversionWindow((state) => ({ ...state, funnel_window_interval_unit }))
                            setConversionWindow()
                        }
                    }}
                    options={options}
                />
            </div>
        </div>
    )
}
