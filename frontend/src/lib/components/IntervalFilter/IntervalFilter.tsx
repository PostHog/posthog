import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightQueryNode } from '~/queries/schema'

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
            <LemonSelect
                size={'small'}
                disabled={disabled}
                value={interval || 'day'}
                dropdownMatchSelectWidth={false}
                onChange={(value) => {
                    updateQuerySource({ interval: value } as Partial<InsightQueryNode>)
                }}
                data-attr="interval-filter"
                options={Object.entries(enabledIntervals).map(([value, { label, disabledReason }]) => ({
                    value,
                    label,
                    disabledReason,
                }))}
            />
        </>
    )
}
