import { useValues, useActions } from 'kea'
import { compareFilterLogic } from './compareFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonCheckbox } from '@posthog/lemon-ui'

export function CompareFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { compare, disabled } = useValues(compareFilterLogic(insightProps))
    const { setCompare } = useActions(compareFilterLogic(insightProps))

    // Hide compare filter control when disabled to avoid states where control is "disabled but checked"
    if (disabled) {
        return null
    }

    return (
        <LemonCheckbox
            onChange={setCompare}
            checked={compare}
            disabled={disabled}
            label={<span className="font-normal">Compare to previous time period</span>}
            bordered
            size="small"
        />
    )
}
