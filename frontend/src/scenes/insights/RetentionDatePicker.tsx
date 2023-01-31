import { useActions, useValues } from 'kea'
import { retentionLogic } from 'scenes/retention/retentionLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import { DatePicker } from 'lib/components/DatePicker'

export function RetentionDatePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(retentionLogic(insightProps))
    const { setFilters } = useActions(retentionLogic(insightProps))

    const yearSuffix = filters.date_to && dayjs(filters.date_to).year() !== dayjs().year() ? ', YYYY' : ''

    return (
        <Tooltip title="Cohorts up to this end date">
            <span style={{ maxWidth: 100 }} className="flex inline-flex items-center pl-2 max-w-40">
                <DatePicker
                    showTime={filters.period === 'Hour'}
                    use12Hours
                    format={filters.period === 'Hour' ? `MMM D${yearSuffix}, h a` : `MMM D${yearSuffix}`}
                    value={filters.date_to ? dayjs(filters.date_to) : undefined}
                    onChange={(date_to) => setFilters({ date_to: date_to && dayjs(date_to).toISOString() })}
                    allowClear
                    placeholder="Today"
                    className="retention-date-picker"
                />
            </span>
        </Tooltip>
    )
}
