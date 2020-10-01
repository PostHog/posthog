import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined } from '@ant-design/icons'
import { retentionTableLogic, dateOptions } from 'scenes/retention/retentionTableLogic'
import { DatePicker, Select } from 'antd'

export function RetentionTab(): JSX.Element {
    const node = useRef()
    const [open, setOpen] = useState<boolean>(false)
    const { filters, startEntity } = useValues(retentionTableLogic)
    const { setFilters } = useActions(retentionTableLogic)

    const entityLogic = entityFilterLogic({
        setFilters: (filters) => {
            setFilters(filters)
            setOpen(false)
        },
        filters: filters,
        typeKey: 'retention-table',
        singleMode: true,
    })

    return (
        <div data-attr="retention-tab">
            <h4 className="secondary">Target Event</h4>
            <button
                ref={node}
                className="filter-action btn btn-sm btn-light"
                type="button"
                onClick={(): void => setOpen(!open)}
                style={{
                    fontWeight: 500,
                }}
            >
                {startEntity?.name || 'Select action'}
                <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />
            </button>
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
            <hr />
            <h4 className="secondary">Start Day</h4>
            <div>
                <DatePicker
                    className="mb-2"
                    value={filters.date_from}
                    onChange={(date): void => setFilters({ date_from: date })}
                    allowClear={false}
                />
            </div>
            <hr />
            <h4 className="secondary">Period</h4>
            <div>
                <Select
                    value={dateOptions[filters.period]}
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
        </div>
    )
}
