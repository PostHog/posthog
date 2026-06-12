import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'

import { insightLogic } from 'scenes/insights/insightLogic'

export function PercentStackViewFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!showPercentStackView}
            onChange={(checked) => {
                updateInsightFilter({ showPercentStackView: checked })
            }}
            label={<span className="font-normal">Show as % of total</span>}
            size="small"
        />
    )
}
