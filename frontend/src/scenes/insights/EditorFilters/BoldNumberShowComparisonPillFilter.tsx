import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { insightLogic } from '../insightLogic'

export function BoldNumberShowComparisonPillFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { trendsFilter, compareFilter } = useValues(insightVizDataLogic(insightProps))

    const checked = !!trendsFilter?.boldNumberShowComparisonPill

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={checked}
            disabledReason={!compareFilter?.compare ? "Enable 'Compare to previous' first" : undefined}
            onChange={() => {
                updateInsightFilter({ boldNumberShowComparisonPill: !checked })
            }}
            label={<span className="font-normal">Show comparison as pill</span>}
            size="small"
        />
    )
}
