import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { DatePicker } from 'lib/components/DatePicker'
import dayjs from 'dayjs'

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
        <>
        <LemonCheckbox
            onChange={(compare: boolean) => {
                if (!compare) {
                    updateInsightFilter({ comparison: undefined })
                }
                updateInsightFilter({ compare })
            }}
            checked={!!compare}
            label={<span className="font-normal">Compare to the period starting</span>}
            size="small"
            className="ml-4"
        />
        <DatePicker
            allowClear={false}
            showTime={false}
            disabled={!compare}
            onSelect={(value: dayjs.Dayjs) => {
                updateInsightFilter({ comparison: {
                    period_start_date: value.toISOString()
                }})
            }}
            size="small"
            className="w-40"
        />
        </>
    )
}
