import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

type LegendPosition = NonNullable<TrendsFilter['legendPosition']>

const OPTIONS: { value: LegendPosition; label: string }[] = [
    { value: 'bottom', label: 'Bottom' },
    { value: 'top', label: 'Top' },
    { value: 'left', label: 'Left' },
    { value: 'right', label: 'Right' },
]

export function LegendPositionFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <span className="font-normal">Legend position</span>
            <LemonSelect
                size="small"
                value={legendPosition ?? 'bottom'}
                options={OPTIONS}
                onChange={(value) => updateInsightFilter({ legendPosition: value })}
            />
        </div>
    )
}
