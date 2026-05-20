import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { LegendPosition } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

const POSITION_OPTIONS: { value: LegendPosition; label: string }[] = [
    { value: LegendPosition.Right, label: 'Right' },
    { value: LegendPosition.Left, label: 'Left' },
    { value: LegendPosition.Top, label: 'Top' },
    { value: LegendPosition.Bottom, label: 'Bottom' },
]

export function ShowLegendFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showLegend, legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowLegend = (): void => {
        updateInsightFilter({ showLegend: !showLegend })
    }

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <LemonCheckbox
                onChange={toggleShowLegend}
                checked={!!showLegend}
                label={<span className="font-normal">Show legend</span>}
                size="small"
            />
            {showLegend && (
                <LemonSelect
                    size="xsmall"
                    value={legendPosition ?? LegendPosition.Right}
                    onChange={(value) => updateInsightFilter({ legendPosition: value })}
                    options={POSITION_OPTIONS}
                    dropdownMatchSelectWidth={false}
                />
            )}
        </div>
    )
}
