import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

type LegendPosition = NonNullable<TrendsFilter['legendPosition']>

const POSITION_OPTIONS: { value: LegendPosition; label: string }[] = [
    { value: 'bottom', label: 'Bottom' },
    { value: 'top', label: 'Top' },
    { value: 'left', label: 'Left' },
    { value: 'right', label: 'Right' },
]

export function LegendOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showLegend, legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <LemonCheckbox
                onChange={(checked) => updateInsightFilter({ showLegend: checked })}
                checked={!!showLegend}
                label={<span className="font-normal">Show legend</span>}
                size="small"
            />
            <LemonSelect
                size="small"
                value={(legendPosition ?? 'bottom') as LegendPosition}
                options={POSITION_OPTIONS}
                disabledReason={!showLegend ? 'Enable the legend to set its position' : undefined}
                onChange={(position) => updateInsightFilter({ legendPosition: position })}
            />
        </div>
    )
}
