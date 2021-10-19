import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Row, Checkbox, Col, Button } from 'antd'
import { BreakdownFilter } from '../../BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { InfoCircleOutlined, PlusCircleOutlined } from '@ant-design/icons'
import { trendsLogic } from '../../../trends/trendsLogic'
import { FilterType, ViewType } from '~/types'
import { Formula } from './Formula'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './TrendTab.scss'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { Tooltip } from 'lib/components/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'

export interface TrendTabProps {
    view: string
}

export function TrendTab({ view }: TrendTabProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(trendsLogic(insightProps))
    const { setFilters, toggleLifecycle } = useActions(trendsLogic(insightProps))
    const { preflight } = useValues(preflightLogic)
    const [isUsingFormulas, setIsUsingFormulas] = useState(filters.formula ? true : false)
    const lifecycles = [
        { name: 'new', tooltip: 'Users that are new.' },
        { name: 'resurrecting', tooltip: 'Users who were once active but became dormant, and are now active again.' },
        { name: 'returning', tooltip: 'Users who consistently use the product.' },
        { name: 'dormant', tooltip: 'Users who are inactive.' },
    ]
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const formulaAvailable =
        (!filters.insight || filters.insight === ViewType.TRENDS) && preflight?.is_clickhouse_enabled
    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 0

    return (
        <>
            <Row gutter={16}>
                <Col md={16} xs={24}>
                    <ActionFilter
                        horizontalUI
                        filters={filters}
                        setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                        typeKey={'trends_' + view}
                        buttonCopy="Add graph series"
                        showSeriesIndicator
                        singleFilter={filters.insight === ViewType.LIFECYCLE}
                        hideMathSelector={filters.insight === ViewType.LIFECYCLE}
                        customRowPrefix={
                            filters.insight === ViewType.LIFECYCLE ? (
                                <>
                                    Showing <b>Unique users</b> who did
                                </>
                            ) : undefined
                        }
                    />
                </Col>
                <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                    {filters.insight === ViewType.LIFECYCLE && (
                        <>
                            <GlobalFiltersTitle unit="actions/events" />
                            <TestAccountFilter filters={filters} onChange={setFilters} />
                            <hr />
                            <h4 className="secondary">Lifecycle Toggles</h4>
                            <div className="toggles">
                                {lifecycles.map((lifecycle, idx) => (
                                    <div key={idx}>
                                        {lifecycle.name}{' '}
                                        <div>
                                            <Checkbox
                                                defaultChecked
                                                className={lifecycle.name}
                                                onChange={() => toggleLifecycle(lifecycle.name)}
                                            />
                                            <Tooltip title={lifecycle.tooltip}>
                                                <InfoCircleOutlined className="info-indicator" />
                                            </Tooltip>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                    {filters.insight !== ViewType.LIFECYCLE && (
                        <>
                            <GlobalFiltersTitle />
                            <PropertyFilters pageKey="trends-filters" />
                            <TestAccountFilter filters={filters} onChange={setFilters} />
                            {formulaAvailable && (
                                <>
                                    <hr />
                                    <h4 className="secondary">
                                        Formula{' '}
                                        <Tooltip
                                            title={
                                                <>
                                                    Apply math operations to your series. You can do operations among
                                                    series (e.g. <code>A / B</code>) or simple arithmetic operations on
                                                    a single series (e.g. <code>A / 100</code>)
                                                </>
                                            }
                                        >
                                            <InfoCircleOutlined />
                                        </Tooltip>
                                    </h4>
                                    {isUsingFormulas ? (
                                        <Row align="middle" gutter={4}>
                                            <Col>
                                                <CloseButton
                                                    onClick={() => {
                                                        setIsUsingFormulas(false)
                                                        setFilters({ formula: undefined })
                                                    }}
                                                />
                                            </Col>
                                            <Col>
                                                <Formula
                                                    filters={filters}
                                                    onChange={(formula: string): void => {
                                                        setFilters({ formula })
                                                    }}
                                                    autoFocus
                                                    allowClear={false}
                                                />
                                            </Col>
                                        </Row>
                                    ) : (
                                        <Tooltip
                                            title={
                                                !formulaEnabled
                                                    ? 'Please add at least one graph series to use formulas'
                                                    : undefined
                                            }
                                            visible={formulaEnabled ? false : undefined}
                                        >
                                            <Button
                                                onClick={() => setIsUsingFormulas(true)}
                                                disabled={!formulaEnabled}
                                                type="link"
                                                style={{ paddingLeft: 0 }}
                                                icon={<PlusCircleOutlined />}
                                                data-attr="btn-add-formula"
                                            >
                                                Add formula
                                            </Button>
                                        </Tooltip>
                                    )}
                                </>
                            )}
                        </>
                    )}
                    {filters.insight !== ViewType.LIFECYCLE && filters.insight !== ViewType.STICKINESS && (
                        <>
                            <hr />
                            <h4 className="secondary">
                                Breakdown by
                                <Tooltip
                                    placement="right"
                                    title="Use breakdown to see the aggregation (total volume, active users, etc.) for each value of that property. For example, breaking down by Current URL with total volume will give you the event volume for each URL your users have visited."
                                >
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </h4>
                            <Row align="middle">
                                <BreakdownFilter filters={filters} setFilters={setFilters} />
                            </Row>
                        </>
                    )}
                </Col>
            </Row>
        </>
    )
}
