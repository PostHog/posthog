import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Tooltip, Row, Skeleton, Checkbox, Col, Button } from 'antd'
import { BreakdownFilter } from '../../BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { InfoCircleOutlined } from '@ant-design/icons'
import { trendsLogic } from '../../../trends/trendsLogic'
import { ViewType } from '../../insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FilterType } from '~/types'
import { Formula } from './Formula'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './TrendTab.scss'
import { TrendTabProps } from './TrendTab'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { InsightTitle } from '../InsightTitle'
import { InsightActionBar } from '../InsightActionBar'

export function TrendTabHorizontal({ view, annotationsToCreate }: TrendTabProps): JSX.Element {
    const { filters, filtersLoading } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)
    const [isUsingFormulas, setIsUsingFormulas] = useState(filters.formula ? true : false)
    const { toggleLifecycle } = useActions(trendsLogic)
    const lifecycles = [
        { name: 'new', tooltip: 'Users that are new.' },
        { name: 'resurrecting', tooltip: 'Users who were once active but became dormant, and are now active again.' },
        { name: 'returning', tooltip: 'Users who consistently use the product.' },
        { name: 'dormant', tooltip: 'Users who are inactive.' },
    ]
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const formulaAvailable =
        (!filters.insight || filters.insight === ViewType.TRENDS) &&
        featureFlags['3275-formulas'] &&
        preflight?.is_clickhouse_enabled
    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 1

    return (
        <>
            <Row gutter={16}>
                <Col md={16} xs={24}>
                    <InsightTitle
                        actionBar={
                            <InsightActionBar
                                filters={filters}
                                annotations={annotationsToCreate}
                                insight={filters.insight}
                            />
                        }
                    />
                    {filtersLoading ? (
                        <div data-test-filters-loading>
                            <Skeleton active />
                        </div>
                    ) : (
                        <ActionFilter
                            horizontalUI
                            filters={filters}
                            setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                            typeKey={'trends_' + view}
                            buttonCopy="Add graph series"
                            showLetters={isUsingFormulas}
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
                    )}
                </Col>
                <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                    {filters.insight === ViewType.LIFECYCLE && (
                        <>
                            <h4 className="secondary">Global Filters</h4>
                            <TestAccountFilter filters={filters} onChange={setFilters} />
                            <hr />
                            <h4 className="secondary">Lifecycle Toggles</h4>
                            {filtersLoading ? (
                                <div data-test-filters-loading>
                                    <Skeleton active />
                                </div>
                            ) : (
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
                            )}
                        </>
                    )}
                    {filters.insight !== ViewType.LIFECYCLE && (
                        <>
                            <h4 className="secondary">Global Filters</h4>
                            {filtersLoading ? (
                                <Skeleton active paragraph={{ rows: 2 }} />
                            ) : (
                                <>
                                    <PropertyFilters pageKey="trends-filters" />
                                    <TestAccountFilter filters={filters} onChange={setFilters} />
                                    {formulaAvailable && (
                                        <>
                                            <hr />
                                            <h4 className="secondary">Formula</h4>
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
                                                            ? 'Please add at least two graph series to use formulas'
                                                            : undefined
                                                    }
                                                >
                                                    <Button
                                                        shape="round"
                                                        onClick={() => setIsUsingFormulas(true)}
                                                        disabled={!formulaEnabled}
                                                    >
                                                        Add formula
                                                    </Button>
                                                </Tooltip>
                                            )}
                                        </>
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
                            {filtersLoading ? (
                                <Skeleton paragraph={{ rows: 0 }} active />
                            ) : (
                                <Row align="middle">
                                    <BreakdownFilter
                                        filters={filters}
                                        onChange={(breakdown: string, breakdown_type: string): void =>
                                            setFilters({ breakdown, breakdown_type })
                                        }
                                    />
                                    {filters.breakdown && (
                                        <CloseButton
                                            onClick={(): void => setFilters({ breakdown: false, breakdown_type: null })}
                                            style={{ marginTop: 1, marginLeft: 5 }}
                                        />
                                    )}
                                </Row>
                            )}
                        </>
                    )}
                </Col>
            </Row>
        </>
    )
}
