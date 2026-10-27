import { useActions, useValues } from 'kea'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { insightLogic } from '../insightLogic'

export function StackBreakdownFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Stack breakdown values"
            checked={!!trendsFilter?.stackBreakdownValues}
            onChange={(checked) => {
                updateInsightFilter({ stackBreakdownValues: checked })
            }}
        />
    )
}
