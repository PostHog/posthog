import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Tooltip, Row, Skeleton, Switch } from 'antd'
import { BreakdownFilter } from '../../BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { InfoCircleOutlined } from '@ant-design/icons'
import { trendsLogic } from '../../../trends/trendsLogic'
import { ViewType } from '../../insightLogic'
import { ShownAsValue } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FilterType } from '~/types'
import { Formula } from './Formula'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './TrendTab.scss'

interface TrendTabProps {
    view: string
}

export function TrendTab({ view }: TrendTabProps): JSX.Element {
    const { filters, filtersLoading } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)
    const [isUsingFormulas, setIsUsingFormulas] = useState(filters.formula ? true : false)
    const { toggleLifecycle } = useActions(trendsLogic)
    const lifecycleNames = ['new', 'resurrecting', 'returning', 'dormant']

    return (
        <>
            <h4 className="secondary">
                {filters.insight === ViewType.LIFECYCLE ? 'Target Action/Event' : 'Actions & Events'}
            </h4>
            {filtersLoading ? (
                <Skeleton active />
            ) : (
                <ActionFilter
                    filters={filters}
                    setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                    typeKey={'trends_' + view}
                    hideMathSelector={filters.shown_as === ShownAsValue.LIFECYCLE}
                    copy="Add graph series"
                    showLetters={isUsingFormulas}
                    disabled={
                        filters.shown_as === ShownAsValue.LIFECYCLE &&
                        !!(filters.events?.length || filters.actions?.length)
                    }
                    singleFilter={filters.shown_as === ShownAsValue.LIFECYCLE}
                    hidePropertySelector={filters.shown_as === ShownAsValue.LIFECYCLE}
                />
            )}

            <hr />
            {filters.insight === ViewType.LIFECYCLE && (
                <>
                    <h4 className="secondary">Lifecycle Toggles</h4>
                    {filtersLoading ? (
                        <Skeleton active />
                    ) : (
                        <div className="toggles">
                            {lifecycleNames.map((cycle, idx) => (
                                <div key={idx}>
                                    {cycle}{' '}
                                    <Switch size="small" defaultChecked onChange={() => toggleLifecycle(cycle)} />
                                </div>
                            ))}
                        </div>
                    )}
                </>
            )}
            <hr />
            <h4 className="secondary">Filters</h4>
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
