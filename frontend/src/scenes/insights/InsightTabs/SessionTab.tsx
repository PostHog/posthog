import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { ViewType } from '../insightLogic'
import { trendsLogic } from '../../trends/trendsLogic'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { FilterType } from '~/types'
import { Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { TestAccountFilter } from '../TestAccountFilter'

export function SessionTab(): JSX.Element {
    const { filters } = useValues(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))
    const { setFilters } = useActions(trendsLogic({ dashboardItemId: null, view: ViewType.SESSIONS }))

    return (
        <>
            <h4 className="secondary">
                Sessions Defined By
                <Tooltip
                    placement="right"
                    title="Select the actions and events that will be considered when determining sessions. If none are selected, the query will attempt to take all events into consideration."
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={'sessions' + ViewType.SESSIONS}
                hideMathSelector={true}
                copy="Add action or event"
                showOr={true}
            />
            <hr />
            <h4 className="secondary">{'Type'}</h4>
            <SessionFilter value={filters.session} onChange={(v: string): void => setFilters({ session: v })} />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-sessions" />
            <TestAccountFilter filters={filters} onChange={setFilters} />
        </>
    )
}
