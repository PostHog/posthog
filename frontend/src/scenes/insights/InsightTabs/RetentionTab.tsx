import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined, InfoCircleOutlined, ExportOutlined } from '@ant-design/icons'
import {
    retentionTableLogic,
    dateOptions,
    retentionOptions,
    retentionOptionDescriptions,
} from 'scenes/retention/retentionTableLogic'
import { Button, DatePicker, Select, Tooltip } from 'antd'
import { Link } from 'lib/components/Link'

export function RetentionTab(): JSX.Element {
    const node = useRef()
    const returningNode = useRef()
    const [open, setOpen] = useState<boolean>(false)
    const [returningOpen, setReturningOpen] = useState<boolean>(false)
    const { filters, startEntity, selectedDate, period, retentionType, returningEntity } = useValues(
        retentionTableLogic({ dashboardItemId: null })
    )
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
            <h4 className="secondary">
                Cohortizing Event
                <Tooltip
                    key="2"
                    placement="right"
                    title={`Event that determines which users are considered to form each cohort (i.e. performed event in ${
                        dateOptions[filters.period]
                    } 0)`}
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>
            <Button
                ref={node}
                data-attr="retention-action"
                onClick={(): void => setOpen(!open)}
                style={{ marginRight: 8 }}
            >
                {startEntity?.name || 'Select action'}
                <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} />
            </Button>
            <Select
                value={retentionOptions[retentionType]}
                onChange={(value): void => setFilters({ retentionType: value })}
                dropdownMatchSelectWidth={false}
                style={{ marginTop: 8 }}
            >
                {Object.entries(retentionOptions).map(([key, value]) => (
                    <Select.Option key={key} value={key}>
                        {value}
                        <Tooltip placement="right" title={retentionOptionDescriptions[key]}>
                            <InfoCircleOutlined className="info-indicator" />
                        </Tooltip>
                    </Select.Option>
                ))}
            </Select>
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
            <h4 style={{ marginTop: '0.5rem' }} className="secondary">
                Retaining event
                <Tooltip
                    key="3"
                    placement="right"
                    title="Event that determines if each user came back on each period (i.e. if they were retained)"
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>

            <Button
                ref={returningNode}
                data-attr="retention-returning-action"
                onClick={(): void => setReturningOpen(!returningOpen)}
            >
                {returningEntity?.name || 'Select action'}
                <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} />
            </Button>
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
            <div className="mt-05">
                <Link
                    to="https://posthog.com/docs/features/retention?utm_campaign=learn-more&utm_medium=in-product"
                    target="_blank"
                    rel="noreferrer noopener"
                >
                    More info on retention <ExportOutlined />
                </Link>
            </div>

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
