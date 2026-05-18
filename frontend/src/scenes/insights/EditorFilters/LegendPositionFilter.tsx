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
            <span className="font-normal">Legend position</span>
            <LemonSelect
                size="small"
                value={legendPosition ?? LegendPosition.Right}
                onChange={(value) => updateInsightFilter({ legendPosition: value })}
                options={[
                    { label: 'Right', value: LegendPosition.Right },
                    { label: 'Bottom', value: LegendPosition.Bottom },
                    { label: 'Top', value: LegendPosition.Top },
                    { label: 'Left', value: LegendPosition.Left },
                ]}
            />
        </div>
    )
}
