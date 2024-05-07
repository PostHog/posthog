import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightQueryNode } from '~/queries/schema'
import { IntervalType } from '~/types'

interface IntervalFilterProps {
    disabled?: boolean
}

export function IntervalFilter({ disabled }: IntervalFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { interval, enabledIntervals } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <>
            <span>
                <span className="hide-lte-md">grouped </span>by
            </span>
            <IntervalFilterStandalone
                disabled={disabled}
                interval={interval || 'day'}
                onIntervalChange={(value) => {
                    updateQuerySource({ interval: value } as Partial<InsightQueryNode>)
                }}
                options={Object.entries(enabledIntervals).reduce(
                    (result: LemonSelectOption<IntervalType>[], [value, { label, disabledReason, hidden }]) => {
                        if (!hidden) {
                            result.push({
                                value: value as IntervalType,
                                label,
                                disabledReason,
                            })
                        }
                        return result
                    },
                    []
                )}
            />
        </>
    )
}

interface IntervalFilterStandaloneProps {
    disabled?: boolean
    interval: IntervalType | undefined
    onIntervalChange: (interval: IntervalType) => void
    options: LemonSelectOption<IntervalType>[]
}

export function IntervalFilterStandalone({
    disabled,
    interval,
    onIntervalChange,
    options,
}: IntervalFilterStandaloneProps): JSX.Element {
    return (
        <LemonSelect
            size="small"
            disabled={disabled}
            value={interval || 'day'}
            dropdownMatchSelectWidth={false}
            onChange={onIntervalChange}
            data-attr="interval-filter"
            options={options}
        />
    )
}
