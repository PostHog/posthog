import React from 'react'
import dayjs from 'dayjs'
import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/es/date-picker/generatePicker'
import { useActions, useValues } from 'kea'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { CalendarOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

export function RetentionDatePicker(): JSX.Element {
    const { filters } = useValues(retentionTableLogic({ dashboardItemId: null }))
    const { setFilters } = useActions(retentionTableLogic({ dashboardItemId: null }))
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
