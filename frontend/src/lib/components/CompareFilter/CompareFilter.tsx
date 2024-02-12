import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function CompareFilter(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { compare, supportsCompare } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const disabled: boolean = !canEditInsight || !supportsCompare

    // Hide compare filter control when disabled to avoid states where control is "disabled but checked"
    if (disabled) {
        return null
    }

    return (
        <LemonCheckbox
            onChange={(compare: boolean) => {
                updateInsightFilter({ compare })
            }}
            checked={!!compare}
            label={<span className="font-normal">Compare to previous period</span>}
            bordered
            size="small"
        />
    )
}
