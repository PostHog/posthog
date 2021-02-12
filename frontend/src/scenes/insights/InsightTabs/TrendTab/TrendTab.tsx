import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Tooltip, Row } from 'antd'
import { BreakdownFilter } from '../../BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { ShownAsFilter } from '../../ShownAsFilter'
import { InfoCircleOutlined } from '@ant-design/icons'
import { trendsLogic } from '../../trendsLogic'
import { ViewType } from '../../insightLogic'
import { ShownAsValue } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FilterType } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { Formula } from './Formula'

interface TrendTabProps {
    view: string
}

export function TrendTab({ view }: TrendTabProps): JSX.Element {
    const { filters } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)

    return featureFlags['remove-shownas'] ? (
        <>
            <h4 className="secondary">
                {filters.insight === ViewType.LIFECYCLE ? 'Target Action/Event' : 'Actions & Events'}
            </h4>
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={'trends_' + view}
                hideMathSelector={filters.shown_as === ShownAsValue.LIFECYCLE}
                copy="Add graph series"
                disabled={
                    filters.shown_as === ShownAsValue.LIFECYCLE && !!(filters.events?.length || filters.actions?.length)
                }
                singleFilter={filters.shown_as === ShownAsValue.LIFECYCLE}
            />
            {filters.insight !== ViewType.LIFECYCLE && (
                <>
                    <hr />
                    <h4 className="secondary">Filters</h4>
                    <PropertyFilters pageKey="trends-filters" />
                </>
            )}
            {(!filters.insight || filters.insight === ViewType.TRENDS) &&
                featureFlags['3275-formulas'] &&
                user?.ee_enabled && (
                    <>
                        <hr />
                        <h4 className="secondary">Formula</h4>
                        <Formula filters={filters} onChange={(formula: string): void => setFilters({ formula })} />
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
                    <Row>
                        <BreakdownFilter
                            filters={filters}
                            onChange={(breakdown: string, breakdown_type: string): void =>
                                setFilters({ breakdown, breakdown_type })
                            }
                        />
                        {filters.breakdown && (
                            <CloseButton
                                onClick={(): void => setFilters({ breakdown: false, breakdown_type: null })}
                                style={{ marginTop: 1, marginLeft: 10 }}
                            />
                        )}
                    </Row>
                </>
            )}
        </>
    ) : (
        <>
            <h4 className="secondary">{'Actions & Events'}</h4>
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey="trends"
                hideMathSelector={filters.shown_as === ShownAsValue.LIFECYCLE}
                copy="Add graph series"
                disabled={
                    filters.shown_as === ShownAsValue.LIFECYCLE && !!(filters.events?.length || filters.actions?.length)
                }
            />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-filters" />
            {(!filters.insight || filters.insight === ViewType.TRENDS) &&
                featureFlags['3275-formulas'] &&
                user?.ee_enabled && (
                    <>
                        <hr />
                        <h4 className="secondary">Formula</h4>
                        <Formula filters={filters} onChange={(formula: string): void => setFilters({ formula })} />
                    </>
                )}
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
            <Row>
                <BreakdownFilter
                    filters={filters}
                    onChange={(breakdown: string, breakdown_type: string): void =>
                        setFilters({ breakdown, breakdown_type })
                    }
                />
                {filters.breakdown && (
                    <CloseButton
                        onClick={(): void => setFilters({ breakdown: false, breakdown_type: null })}
                        style={{ marginTop: 1, marginLeft: 10 }}
                    />
                )}
            </Row>
            <hr />
            <h4 className="secondary">
                Shown as
                <Tooltip
                    placement="right"
                    title='
                                            Stickiness shows you how many days users performed an action within the timeframe. If a user
                                            performed an action on Monday and again on Friday, it would be shown 
                                            as "2 days".'
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>
            <ShownAsFilter filters={filters} onChange={(_filters: Partial<FilterType>): void => setFilters(_filters)} />
        </>
    )
}
