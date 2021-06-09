import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Tooltip, Row, Skeleton, Checkbox } from 'antd'
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
import { TrendTabHorizontal } from './TrendTabHorizontal'
import { FEATURE_FLAGS } from 'lib/constants'
import { BaseTabProps } from 'scenes/insights/Insights'

export interface TrendTabProps extends BaseTabProps {
    view: string
}

export function TrendTab(props: TrendTabProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? <TrendTabHorizontal {...props} /> : <DefaultTrendTab {...props} />
}

function DefaultTrendTab({ view }: TrendTabProps): JSX.Element {
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
            <h4 className="secondary">
                {filters.insight === ViewType.LIFECYCLE ? 'Target Action/Event' : 'Actions & Events'}
            </h4>
            {filtersLoading ? (
                <div data-test-filters-loading>
                    <Skeleton active />
                </div>
            ) : (
                <ActionFilter
                    filters={filters}
                    setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                    typeKey={'trends_' + view}
                    buttonCopy="Add graph series"
                    showLetters={isUsingFormulas}
                    singleFilter={filters.insight === ViewType.LIFECYCLE}
                    hidePropertySelector={filters.insight === ViewType.LIFECYCLE}
                />
            )}

            {filters.insight === ViewType.LIFECYCLE && (
                <>
                    <hr />
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
            <hr />
            <h4 className="secondary">Filters</h4>
            {filtersLoading ? (
                <div data-test-filters-loading>
                    <Skeleton active paragraph={{ rows: 2 }} />
                </div>
            ) : (
                <>
                    <PropertyFilters pageKey="trends-filters" />
                    <TestAccountFilter filters={filters} onChange={setFilters} />
                    {(!filters.insight || filters.insight === ViewType.TRENDS) &&
                        featureFlags['3275-formulas'] &&
                        preflight?.is_clickhouse_enabled && (
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
                        Break down by
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
        </>
    )
}
