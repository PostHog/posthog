import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { EditorFilterProps, FunnelConversionWindowTimeUnit } from '~/types'

import { TIME_INTERVAL_BOUNDS, funnelConversionWindowFilterLogic } from './funnelConversionWindowFilterLogic'

export function FunnelConversionWindowFilter({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { querySource } = useValues(funnelDataLogic(insightProps))
    const { funnelWindowInterval, funnelWindowIntervalUnit, isOutOfBounds, validationError } = useValues(
        funnelConversionWindowFilterLogic(insightProps)
    )
    const { setFunnelWindowInterval, setFunnelWindowIntervalUnit, commitFilter } = useActions(
        funnelConversionWindowFilterLogic(insightProps)
    )

    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(funnelWindowInterval ?? 7, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )

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
                        value={funnelWindowInterval ?? undefined}
                        onChange={(value) => {
                            setFunnelWindowInterval(Number(value))
                        }}
                        onBlur={commitFilter}
                        onPressEnter={commitFilter}
                    />
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        value={funnelWindowIntervalUnit}
                        onChange={(unit: FunnelConversionWindowTimeUnit | null) => {
                            if (unit) {
                                setFunnelWindowIntervalUnit(unit)
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
