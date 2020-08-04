import React from 'react'
import { ViewType } from '../insightLogic'
import { RetentionTab } from './RetentionTab'
import { SessionTab } from './SessionTab'
import { TrendTab } from './TrendTab'
import { PathTab } from './PathTab'
import { FunnelTab } from './FunnelTab'

export const insightFilters = {
    [`${ViewType.TRENDS}`]: <TrendTab></TrendTab>,
    [`${ViewType.SESSIONS}`]: <SessionTab />,
    [`${ViewType.FUNNELS}`]: <FunnelTab></FunnelTab>,
    [`${ViewType.RETENTION}`]: <RetentionTab></RetentionTab>,
    [`${ViewType.PATHS}`]: <PathTab></PathTab>,
}
