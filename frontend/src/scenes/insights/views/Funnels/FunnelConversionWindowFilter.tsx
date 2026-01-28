import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelConversionWindowTimeUnit } from '~/types'

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

    const [localConversionWindow, setLocalConversionWindow] = useState<{
        funnelWindowInterval: number | undefined
        funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit
    }>({
        funnelWindowInterval,
        funnelWindowIntervalUnit,
    })

    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(funnelWindowInterval ?? 7, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )
    const localInterval = localConversionWindow.funnelWindowInterval
    const localUnit = localConversionWindow.funnelWindowIntervalUnit
    const [minBound, maxBound] = TIME_INTERVAL_BOUNDS[localUnit ?? FunnelConversionWindowTimeUnit.Day]

    const isValidNumber = localInterval !== undefined && !Number.isNaN(localInterval)
    const isOutOfBounds = isValidNumber && (localInterval < minBound || localInterval > maxBound)
    const validationError = isOutOfBounds ? `Value must be between ${minBound} and ${maxBound}` : undefined

    const setConversionWindow = useDebouncedCallback((): void => {
        if (!isValidNumber || isOutOfBounds) {
            return
        }

        if (localInterval !== funnelWindowInterval || localUnit !== funnelWindowIntervalUnit) {
            updateInsightFilter(localConversionWindow)
        }
    }, 200)

    return (
        <div className="flex items-start gap-2">
            <span className="flex whitespace-nowrap h-10 items-center">
                Conversion window limit
                <Tooltip
                    title={
                        <>
                            Limit to {aggregationTargetLabel.plural}{' '}
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
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="number"
                        className="max-w-20"
                        fullWidth={false}
                        status={isOutOfBounds ? 'danger' : 'default'}
                        value={localConversionWindow.funnelWindowInterval}
                        onChange={(value) => {
                            setLocalConversionWindow((state) => ({
                                ...state,
                                funnelWindowInterval: Number(value),
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
                {validationError && <p className="text-danger text-xs m-0">{validationError}</p>}
            </div>
        </div>
    )
}
