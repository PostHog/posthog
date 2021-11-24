import React from 'react'
import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/lib/date-picker/generatePicker'
import { useActions, useValues } from 'kea'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { CalendarOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

export function RetentionDatePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(retentionTableLogic(insightProps))
    const { setFilters } = useActions(retentionTableLogic(insightProps))
    const yearSuffix = filters.date_to && dayjs(filters.date_to).year() !== dayjs().year() ? ', YYYY' : ''
    return (
        <>
            <Tooltip title="Cohorts up to this end date">
                <span style={{ maxWidth: 100, display: 'inline-flex', alignItems: 'center' }}>
                    <CalendarOutlined />
                    <DatePicker
                        showTime={filters.period === 'Hour'}
                        use12Hours
                        format={filters.period === 'Hour' ? `MMM D${yearSuffix}, h a` : `MMM D${yearSuffix}`}
                        value={filters.date_to ? dayjs(filters.date_to) : undefined}
                        onChange={(date_to) => setFilters({ date_to: date_to && dayjs(date_to).toISOString() })}
                        allowClear
                        placeholder="Today"
                        className="retention-date-picker"
                        suffixIcon={null}
                    />
                </span>
            </Tooltip>
        </>
    )
}
