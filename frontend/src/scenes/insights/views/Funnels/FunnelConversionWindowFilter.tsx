import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelConversionWindow, FunnelConversionWindowTimeUnit } from '~/types'

export const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
    [FunnelConversionWindowTimeUnit.Second]: [1, 3600],
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

const DEFAULT_FUNNEL_WINDOW_INTERVAL = 14

export function FunnelConversionWindowFilter({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { insightFilter, querySource } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const {
        funnelWindowInterval = DEFAULT_FUNNEL_WINDOW_INTERVAL,
        funnelWindowIntervalUnit = FunnelConversionWindowTimeUnit.Day,
    } = (insightFilter || {}) as FunnelsFilter

    const [localConversionWindow, setLocalConversionWindow] = useState<FunnelConversionWindow>({
        funnelWindowInterval,
        funnelWindowIntervalUnit,
    })

    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(funnelWindowInterval ?? 7, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )
    const intervalBounds = TIME_INTERVAL_BOUNDS[funnelWindowIntervalUnit ?? FunnelConversionWindowTimeUnit.Day]

    const setConversionWindow = useDebouncedCallback((): void => {
        if (Number.isNaN(localConversionWindow.funnelWindowInterval)) {
            return
        }

        if (
            localConversionWindow.funnelWindowInterval !== funnelWindowInterval ||
            localConversionWindow.funnelWindowIntervalUnit !== funnelWindowIntervalUnit
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
                    value={localConversionWindow.funnelWindowInterval || funnelWindowInterval}
                    onChange={(funnelWindowInterval) => {
                        setLocalConversionWindow((state) => ({
                            ...state,
                            funnelWindowInterval: Number(funnelWindowInterval),
                        }))
                        setConversionWindow()
                    }}
                    onBlur={setConversionWindow}
                    onPressEnter={setConversionWindow}
                />
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    value={localConversionWindow.funnelWindowIntervalUnit}
                    onChange={(funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | null) => {
                        if (funnelWindowIntervalUnit) {
                            setLocalConversionWindow((state) => ({ ...state, funnelWindowIntervalUnit }))
                            setConversionWindow()
                        }
                    }}
                    options={options}
                />
            </div>
        </div>
    )
}
