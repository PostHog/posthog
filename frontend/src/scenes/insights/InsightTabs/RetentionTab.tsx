import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined } from '@ant-design/icons'
import { retentionTableLogic, dateOptions, retentionOptions } from 'scenes/retention/retentionTableLogic'
import { DatePicker, Select } from 'antd'

export function RetentionTab(): JSX.Element {
    const node = useRef()
    const [open, setOpen] = useState<boolean>(false)
    const [returningOpen, setReturningOpen] = useState<boolean>(false)
    const { filters, startEntity, selectedDate, period, retentionType, returningEntity } = useValues(
        retentionTableLogic
    )
    const { setFilters } = useActions(retentionTableLogic)

    const entityLogic = entityFilterLogic({
        setFilters: (filters) => {
            setFilters({ startEntity: filters })
            setOpen(false)
        },
        filters: filters.startEntity,
        typeKey: 'retention-table',
        singleMode: true,
    })

    const entityLogicReturning = entityFilterLogic({
        setFilters: (filters) => {
            setFilters({ returningEntity: filters })
            setReturningOpen(false)
        },
        filters: filters.returningEntity,
        typeKey: 'retention-table-returning',
        singleMode: true,
    })

    return (
        <div data-attr="retention-tab">
            <h4 className="secondary">Retention Type</h4>
            <div>
                <Select
                    value={retentionOptions[retentionType]}
                    onChange={(value): void => setFilters({ retentionType: value })}
                    dropdownMatchSelectWidth={false}
                >
                    {Object.entries(retentionOptions).map(([key, value]) => (
                        <Select.Option key={key} value={key}>
                            {value}
                        </Select.Option>
                    ))}
                </Select>
            </div>
            <hr />
            <h4 className="secondary">{retentionType === 'retention_first_time' ? 'First Event' : 'Target Event'}</h4>
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
            {retentionType === 'retention_first_time' && (
                <>
                    <h4 style={{ marginTop: '0.5rem' }} className="secondary">
                        {'Retained event'}
                    </h4>
                    <button
                        ref={node}
                        className="filter-action btn btn-sm btn-light"
                        type="button"
                        onClick={(): void => setReturningOpen(!returningOpen)}
                        style={{
                            fontWeight: 500,
                        }}
                    >
                        {returningEntity?.name || 'Select action'}
                        <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />
                    </button>
                    {returningOpen && (
                        <ActionFilterDropdown
                            logic={entityLogicReturning}
                            onClickOutside={(e): void => {
                                if (node.current.contains(e.target)) {
                                    return
                                }
                                setReturningOpen(false)
                            }}
                        />
                    )}
                </>
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
                        className="mb-2"
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
