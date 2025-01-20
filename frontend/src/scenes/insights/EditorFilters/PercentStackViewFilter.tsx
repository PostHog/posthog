import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { insightLogic } from '../insightLogic'

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
