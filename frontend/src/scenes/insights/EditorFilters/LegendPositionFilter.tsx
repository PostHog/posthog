import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { LegendPosition } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function LegendPositionFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <span id="legend-position-label" className="font-normal">
                Legend position
            </span>
            <LemonSelect
                size="small"
                aria-labelledby="legend-position-label"
                value={legendPosition}
                onChange={(value) => updateInsightFilter({ legendPosition: value })}
                options={[
                    { label: 'Top', value: LegendPosition.Top },
                    { label: 'Right', value: LegendPosition.Right },
                    { label: 'Bottom', value: LegendPosition.Bottom },
                    { label: 'Left', value: LegendPosition.Left },
                ]}
            />
        </div>
    )
}
