import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Tooltip, Row, Skeleton, Checkbox, Col, Button } from 'antd'
import { BreakdownFilter } from '../../BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { InfoCircleOutlined, SaveOutlined } from '@ant-design/icons'
import { trendsLogic } from '../../../trends/trendsLogic'
import { ViewType } from '../../insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FilterType } from '~/types'
import { Formula } from './Formula'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './TrendTab.scss'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { TrendTabProps } from './TrendTab'

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

    return (
        <>
            <Row gutter={16}>
                <Col md={16}>
                    <h3 className="l3" style={{ display: 'flex', alignItems: 'center' }}>
                        Unsaved query{' '}
                        <SaveToDashboard
                            displayComponent={<Button type="link" size="small" icon={<SaveOutlined />} />}
                            item={{
                                entity: {
                                    filters: filters,
                                    annotations: annotationsToCreate,
                                },
                            }}
                        />
                    </h3>
                    {filtersLoading ? (
                        <Skeleton active />
                    ) : (
                        <ActionFilter
                            horizontalUI
                            filters={filters}
                            setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                            typeKey={'trends_' + view}
                            buttonCopy="Add graph series"
                            showLetters={isUsingFormulas}
                            singleFilter={filters.insight === ViewType.LIFECYCLE}
                            hidePropertySelector={filters.insight === ViewType.LIFECYCLE}
                        />
                    )}
                </Col>
                <Col md={8}>
                    {filters.insight === ViewType.LIFECYCLE && (
                        <>
                            <h4 className="secondary">Lifecycle Toggles</h4>
                            {filtersLoading ? (
                                <Skeleton active />
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
                    <h4 className="secondary">Global Filters</h4>
                    {filtersLoading ? (
                        <Skeleton active paragraph={{ rows: 2 }} />
                    ) : (
                        <>
                            <PropertyFilters pageKey="trends-filters" />
                            <TestAccountFilter filters={filters} onChange={setFilters} />
                            {(!filters.insight || filters.insight === ViewType.TRENDS) &&
                                featureFlags['3275-formulas'] &&
                                preflight?.ee_enabled && (
                                    <>
                                        <hr />
                                        <h4 className="secondary">Formula</h4>
                                        <Formula
                                            filters={filters}
                                            onFocus={(hasFocus, localFormula) =>
                                                setIsUsingFormulas(hasFocus ? true : localFormula ? true : false)
                                            }
                                            onChange={(formula: string): void => {
                                                setIsUsingFormulas(formula ? true : false)
                                                setFilters({ formula })
                                            }}
                                        />
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
