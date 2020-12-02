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
import { LIFECYCLE } from 'lib/constants'

export function TrendTab(): JSX.Element {
    const { filters } = useValues(trendsLogic({ dashboardItemId: null, view: ViewType.TRENDS }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view: ViewType.TRENDS }))

    return (
        <>
            <h4 className="secondary">{'Actions & Events'}</h4>
            <ActionFilter
                filters={filters}
                setFilters={(payload): void => setFilters(payload)}
                typeKey="trends"
                hideMathSelector={filters.shown_as === LIFECYCLE}
                copy="Add graph series"
                disabled={filters.shown_as === LIFECYCLE && (filters.events?.length || filters.actions?.length)}
            />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-filters" />
            <hr />
            <h4 className="secondary">
                Break down by
                <Tooltip
                    placement="right"
                    title="Use breakdown to see the volume of events for each variation of that property. For example, breaking down by $current_url will give you the event volume for each url your users have visited."
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>
            <Row>
                <BreakdownFilter
                    filters={filters}
                    onChange={(breakdown, breakdown_type): void => setFilters({ breakdown, breakdown_type })}
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
            <ShownAsFilter filters={filters} onChange={(filters): void => setFilters(filters)} />
        </>
    )
}
