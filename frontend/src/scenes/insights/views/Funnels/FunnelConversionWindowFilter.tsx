import { InfoCircleOutlined } from '@ant-design/icons'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { useState } from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelConversionWindow, FunnelConversionWindowTimeUnit } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useDebouncedCallback } from 'use-debounce'
import { LemonInput, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

export function FunnelConversionWindowFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { conversionWindow, aggregationTargetLabel, filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    const [localConversionWindow, setLocalConversionWindow] = useState<FunnelConversionWindow>(conversionWindow)

    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(
                pluralize(conversionWindow.funnel_window_interval ?? 7, unit, `${unit}s`, false)
            ),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )
    const intervalBounds =
        TIME_INTERVAL_BOUNDS[conversionWindow.funnel_window_interval_unit ?? FunnelConversionWindowTimeUnit.Day]

    const setConversionWindow = useDebouncedCallback((): void => {
        if (
            localConversionWindow.funnel_window_interval !== conversionWindow.funnel_window_interval ||
            localConversionWindow.funnel_window_interval_unit !== conversionWindow.funnel_window_interval_unit
        ) {
            setFilters(localConversionWindow)
        }
    }, 200)

    return (
        <div className={'flex items-center gap-2 '}>
            <span className="whitespace-nowrap">
                Conversion window limit{' '}
                <Tooltip
                    title={
                        <>
                            <b>Recommended!</b> Limit to {aggregationTargetLabel.plural}{' '}
                            {filters.aggregation_group_type_index != undefined ? 'that' : 'who'} converted within a
                            specific time frame. {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                            {filters.aggregation_group_type_index != undefined ? 'that' : 'who'} do not convert in this
                            time frame will be considered as drop-offs.
                        </>
                    }
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </span>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="number"
                    className="max-w-20"
                    fullWidth={false}
                    min={intervalBounds[0]}
                    max={intervalBounds[1]}
                    defaultValue={conversionWindow.funnel_window_interval}
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
