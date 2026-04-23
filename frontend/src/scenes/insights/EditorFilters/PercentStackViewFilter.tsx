import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { insightLogic } from '../insightLogic'

export function PercentStackViewFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentStackView } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonSwitch
            className="px-2 py-1"
            checked={!!showPercentStackView}
            onChange={(checked) => updateInsightFilter({ showPercentStackView: checked })}
            label="Show as % of total"
            fullWidth
        />
    )
}
