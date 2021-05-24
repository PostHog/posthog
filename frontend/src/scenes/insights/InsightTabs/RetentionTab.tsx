import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterRow/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined, InfoCircleOutlined, ExportOutlined } from '@ant-design/icons'
import {
    retentionTableLogic,
    dateOptions,
    retentionOptions,
    retentionOptionDescriptions,
} from 'scenes/retention/retentionTableLogic'
import { Button, Select, Tooltip } from 'antd'
import { Link } from 'lib/components/Link'
import { CloseButton } from 'lib/components/CloseButton'
import dayjs from 'dayjs'
import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/es/date-picker/generatePicker'
import { FilterType } from '~/types'
import { TestAccountFilter } from '../TestAccountFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './RetentionTab.scss'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { RetentionTabHorizontal } from './RetentionTabHorizontal'
import { FEATURE_FLAGS } from 'lib/constants'
import { BaseTabProps } from '../Insights'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

export function RetentionTab(props: BaseTabProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? <RetentionTabHorizontal {...props} /> : <DefaultRetentionTab />
}

function DefaultRetentionTab(): JSX.Element {
    const node = useRef<HTMLElement>(null)
    const returningNode = useRef<HTMLElement>(null)
    const [open, setOpen] = useState<boolean>(false)
    const [returningOpen, setReturningOpen] = useState<boolean>(false)
    const { filters, actionsLookup } = useValues(retentionTableLogic({ dashboardItemId: null }))
    const { setFilters } = useActions(retentionTableLogic({ dashboardItemId: null }))

    const entityLogic = entityFilterLogic({
        setFilters: (filters: FilterType) => {
            if (filters.events && filters.events.length > 0) {
                setFilters({ target_entity: filters.events[0] })
            } else if (filters.actions && filters.actions.length > 0) {
                setFilters({ target_entity: filters.actions[0] })
            } else {
                setFilters({ target_entity: null })
            }
            setOpen(false)
        },
        filters: filters.target_entity,
        typeKey: 'retention-table',
        singleMode: true,
    })

    const entityLogicReturning = entityFilterLogic({
        setFilters: (filters: FilterType) => {
            if (filters.events && filters.events.length > 0) {
                setFilters({ returning_entity: filters.events[0] })
            } else if (filters.actions && filters.actions.length > 0) {
                setFilters({ returning_entity: filters.actions[0] })
            } else {
                setFilters({ returning_entity: null })
            }
            setReturningOpen(false)
        },
        filters: filters.returning_entity,
        typeKey: 'retention-table-returning',
        singleMode: true,
    })

    const selectedRetainingEvent =
        filters.returning_entity?.name ||
        (filters.returning_entity.id && actionsLookup[filters.returning_entity.id]) ||
        'Select action'

    const selectedCohortizingEvent =
        filters.target_entity?.name ||
        (filters.target_entity.id && actionsLookup[filters.target_entity.id]) ||
        'Select action'

    return (
        <div data-attr="retention-tab" className="retention-tab">
            <h4 className="secondary">
                Cohortizing Event
                <Tooltip
                    key="2"
                    placement="right"
                    title={`Event that determines which users are considered to form each cohort (i.e. performed event in ${filters.period} 0)`}
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>
            <div style={{ display: '-webkit-inline-box', flexWrap: 'wrap' }}>
                <Button
                    ref={node}
                    data-attr="retention-action"
                    onClick={(): void => setOpen(!open)}
                    style={{ marginRight: 8, marginBottom: 8 }}
                    className="btn-retention-dropdown"
                >
                    <PropertyKeyInfo value={selectedCohortizingEvent} />
                    <DownOutlined className="dropdown-indicator" />
                </Button>
                <Select
                    value={retentionOptions[filters.retention_type]}
                    onChange={(value): void => setFilters({ retention_type: value })}
                    dropdownMatchSelectWidth={false}
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
                <ActionFilterDropdown
                    open={open}
                    logic={entityLogic as any}
                    openButtonRef={node}
                    onClose={() => setOpen(false)}
                />
            </div>
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
                className="btn-retention-dropdown"
            >
                <PropertyKeyInfo value={selectedRetainingEvent} />
                <DownOutlined className="dropdown-indicator" />
            </Button>
            <ActionFilterDropdown
                open={returningOpen}
                logic={entityLogicReturning as any}
                openButtonRef={returningNode}
                onClose={() => setReturningOpen(false)}
            />
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
            <TestAccountFilter filters={filters} onChange={setFilters} />
            <>
                <hr />
                <h4 className="secondary">Current Date</h4>
                <div>
                    <DatePicker
                        showTime={filters.period === 'Hour'}
                        use12Hours
                        format={filters.period === 'Hour' ? 'YYYY-MM-DD, h a' : 'YYYY-MM-DD'}
                        className="mb-05"
                        value={filters.date_to && dayjs(filters.date_to)}
                        onChange={(date_to): void => setFilters({ date_to: date_to && dayjs(date_to).toISOString() })}
                        allowClear={false}
                    />
                    {filters.date_to && (
                        <CloseButton
                            onClick={() => setFilters({ date_to: null })}
                            style={{
                                marginLeft: 8,
                            }}
                        />
                    )}
                </div>
                <hr />
                <h4 className="secondary">Period</h4>
                <div>
                    <Select
                        value={filters.period}
                        onChange={(value): void => setFilters({ period: value })}
                        dropdownMatchSelectWidth={false}
                    >
                        {dateOptions.map((period) => (
                            <Select.Option key={period} value={period}>
                                {period}
                            </Select.Option>
                        ))}
                    </Select>
                </div>
            </>
        </div>
    )
}
