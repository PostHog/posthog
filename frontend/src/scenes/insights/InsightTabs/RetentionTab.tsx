import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined } from '@ant-design/icons'
import { retentionTableLogic, dateOptions } from 'scenes/retention/retentionTableLogic'
import { Button, DatePicker, Select } from 'antd'

export function RetentionTab(): JSX.Element {
    const node = useRef()
    const [open, setOpen] = useState<boolean>(false)
    const { filters, startEntity, selectedDate, period } = useValues(retentionTableLogic({ dashboardItemId: null }))
    const { setFilters } = useActions(retentionTableLogic({ dashboardItemId: null }))

    const entityLogic = entityFilterLogic({
        setFilters: (filters) => {
            setFilters({ startEntity: filters })
            setOpen(false)
        },
        filters: filters.startEntity,
        typeKey: 'retention-table',
        singleMode: true,
    })

    return (
        <div data-attr="retention-tab">
            <h4 className="secondary">Target Event</h4>
            <Button ref={node} data-attr="retention-action" onClick={(): void => setOpen(!open)}>
                {startEntity?.name || 'Select action'}
                <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} />
            </Button>
            {open && (
                <ActionFilterDropdown
                    logic={entityLogic}
                    onClickOutside={(e): void => {
                        if (node.current.contains(e.target)) {
                            return
                        }
                        setOpen(false)
                    }}
                />
            )}
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="insight-retention" />
            <>
                <hr />
                <h4 className="secondary">Current Date</h4>
                <div>
                    <DatePicker
                        showTime={filters.period === 'h'}
                        use12Hours
                        format={filters.period === 'h' ? 'YYYY-MM-DD, h a' : 'YYYY-MM-DD'}
                        className="mb-05"
                        value={selectedDate}
                        onChange={(date): void => setFilters({ selectedDate: date })}
                        allowClear={false}
                    />
                </div>
                <hr />
                <h4 className="secondary">Period</h4>
                <div>
                    <Select
                        value={dateOptions[period]}
                        onChange={(value): void => setFilters({ period: value })}
                        dropdownMatchSelectWidth={false}
                    >
                        {Object.entries(dateOptions).map(([key, value]) => (
                            <Select.Option key={key} value={key}>
                                {value}
                            </Select.Option>
                        ))}
                    </Select>
                </div>
            </>
        </div>
    )
}
