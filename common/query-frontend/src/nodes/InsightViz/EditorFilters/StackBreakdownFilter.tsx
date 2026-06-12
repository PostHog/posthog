import { useActions, useValues } from 'kea'

import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from 'scenes/insights/insightLogic'

export function StackBreakdownFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!trendsFilter?.stackBreakdownValues}
            onChange={(checked) => {
                updateInsightFilter({ stackBreakdownValues: checked })
            }}
            label={<span className="font-normal">Stack breakdown values</span>}
            size="small"
        />
    )
}
