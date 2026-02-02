import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

export function FillEmptyFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { isTrends, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isTrends) {
        return null
    }

    const toggleFillEmpty = (): void => {
        updateInsightFilter({ fillEmptyWithPrevious: !trendsFilter?.fillEmptyWithPrevious })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleFillEmpty}
            checked={!!trendsFilter?.fillEmptyWithPrevious}
            label={<span className="font-normal">Fill gaps with previous value</span>}
            size="small"
        />
    )
}
