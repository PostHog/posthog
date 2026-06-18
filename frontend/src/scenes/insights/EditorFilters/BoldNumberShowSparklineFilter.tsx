import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { insightLogic } from '../insightLogic'

export function BoldNumberShowSparklineFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))

    const checked = !!trendsFilter?.boldNumberShowSparkline

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={checked}
            onChange={() => {
                updateInsightFilter({ boldNumberShowSparkline: !checked })
            }}
            label={<span className="font-normal">Show sparkline</span>}
            size="small"
        />
    )
}
