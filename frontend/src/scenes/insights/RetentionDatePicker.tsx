import { useActions, useValues } from 'kea'
import { DatePicker } from 'lib/components/DatePicker'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionDatePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { dateRange, retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))

    const period = retentionFilter?.period
    const date_to = dateRange?.date_to

    const yearSuffix = date_to && dayjs(date_to).year() !== dayjs().year() ? ', YYYY' : ''

    return (
        <Tooltip title="Cohorts up to this end date">
            <span className="flex inline-flex items-center pl-2 max-w-[100px]">
                <DatePicker
                    showTime={period === 'Hour'}
                    use12Hours
                    format={period === 'Hour' ? `MMM D${yearSuffix}, h a` : `MMM D${yearSuffix}`}
                    value={date_to ? dayjs(date_to) : undefined}
                    onChange={(date_to) => {
                        updateDateRange({ date_to: date_to && dayjs(date_to).toISOString() })
                    }}
                    allowClear
                    placeholder="Today"
                    className="retention-date-picker"
                />
            </span>
        </Tooltip>
    )
}
