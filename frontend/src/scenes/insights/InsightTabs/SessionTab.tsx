import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { trendsLogic } from '../../trends/trendsLogic'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { FilterType, ViewType } from '~/types'
import { Col, Row } from 'antd'
import { TestAccountFilter } from '../TestAccountFilter'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { GlobalFiltersTitle } from '../common'
import { InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'

export function SessionTab(): JSX.Element {
    const { filters } = useValues(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <Row gutter={16}>
            <Col md={16} xs={24}>
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
                <Row className="mt">
                    <span className="text-muted">
                        Sessions are calculated based on the events you specify above. After 30min of inactivity a new
                        session will be counted.{' '}
                        <Tooltip title="Example: If you select a Pageview event, the session will include all pageviews that happened in sequence without a break longer than 30min in between. Its duration will be the time taken from the first to the last event, or 0 if there was only 1 event.">
                            <InfoCircleOutlined />
                        </Tooltip>
                    </span>
                </Row>
            </Col>
            <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                <GlobalFiltersTitle unit="actions/events" />
                <PropertyFilters pageKey="insight-retention" />
                <TestAccountFilter filters={filters} onChange={setFilters} />
            </Col>
        </Row>
    )
}
