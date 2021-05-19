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
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SessionTabHorizontal } from './SessionTabHorizontal'
import { FEATURE_FLAGS } from 'lib/constants'
import { BaseTabProps } from '../Insights'

export function SessionTab(props: BaseTabProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? <SessionTabHorizontal {...props} /> : <DefaultSessionTab />
}

function DefaultSessionTab(): JSX.Element {
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
                buttonCopy="Add action or event"
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
