import { useActions, useValues } from 'kea'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { insightLogic } from '../insightLogic'

export function PercentStackViewFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Show as % of total"
            checked={!!showPercentStackView}
            onChange={(checked) => {
                updateInsightFilter({ showPercentStackView: checked })
            }}
        />
    )
}
