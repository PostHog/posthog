import { useActions, useValues } from 'kea'
import { retentionLogic } from 'scenes/retention/retentionLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import { DatePicker } from 'lib/components/DatePicker'
import { DateRange } from '~/queries/schema'
import { insightDataLogic } from './insightDataLogic'

export function RetentionDatePickerDataExploration(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { dateRange, retentionFilter } = useValues(insightDataLogic(insightProps))
    const { updateDateRange } = useActions(insightDataLogic(insightProps))

    return (
        <RetentionDatePickerComponent
            period={retentionFilter?.period}
            date_to={dateRange?.date_to}
            updateDateRange={updateDateRange}
        />
    )
}

export function RetentionDatePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(retentionLogic(insightProps))
    const { setFilters } = useActions(retentionLogic(insightProps))

    return (
        <RetentionDatePickerComponent period={filters.period} date_to={filters.date_to} updateDateRange={setFilters} />
    )
}

type RetentionDatePickerComponentProps = {
    period?: string
    date_to?: string | null
    updateDateRange: (filters: Partial<DateRange>) => void
}

function RetentionDatePickerComponent({
    date_to,
    period,
    updateDateRange,
}: RetentionDatePickerComponentProps): JSX.Element {
    const yearSuffix = date_to && dayjs(date_to).year() !== dayjs().year() ? ', YYYY' : ''

    return (
        <Tooltip title="Cohorts up to this end date">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <span style={{ maxWidth: 100 }} className="flex inline-flex items-center pl-2">
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
