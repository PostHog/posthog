import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { trendsLogic } from '../../trends/trendsLogic'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { FilterType, ViewType } from '~/types'
import { Col, Row, Skeleton } from 'antd'
import { TestAccountFilter } from '../TestAccountFilter'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { BaseTabProps } from '../Insights'
import { InsightTitle } from './InsightTitle'
import { InsightActionBar } from './InsightActionBar'
import { GlobalFiltersTitle } from '../common'

export function SessionTab({ annotationsToCreate }: BaseTabProps): JSX.Element {
    const { filters, filtersLoading } = useValues(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <Row gutter={16}>
            <Col md={16} xs={24}>
                <InsightTitle
                    actionBar={
                        <InsightActionBar filters={filters} annotations={annotationsToCreate} insight="SESSIONS" />
                    }
                />
                <Row gutter={8} align="middle" className="mb">
                    <Col>Showing</Col>
                    <Col>
                        <SessionFilter value={filters.session} onChange={(v: string) => setFilters({ session: v })} />
                    </Col>
                    <Col>where a user did any of the following:</Col>
                    <Col />
                </Row>
                <ActionFilter
                    filters={filters}
                    setFilters={(payload: Partial<FilterType>) => setFilters(payload)}
                    typeKey={'sessions' + ViewType.SESSIONS}
                    hideMathSelector={true}
                    buttonCopy="Add action or event"
                    showOr={true}
                    horizontalUI
                    customRowPrefix=""
                />
            </Col>
            <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                <GlobalFiltersTitle unit="actions/events" />
                {filtersLoading ? (
                    <Skeleton active paragraph={{ rows: 1 }} />
                ) : (
                    <>
                        <PropertyFilters pageKey="insight-retention" />
                        <TestAccountFilter filters={filters} onChange={setFilters} />
                    </>
                )}
            </Col>
        </Row>
    )
}
