import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'

export function BIDashboardFilterStatus({
    dashboardId,
    tileId,
}: {
    dashboardId: number
    tileId: number
}): JSX.Element | null {
    const { selection, targets } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (!selection) {
        return null
    }
    const filtered = !!targets[tileId]
    const isSource = selection.tileId === tileId
    const active = filtered || isSource
    const filterStatus = filtered ? 'filtered' : isSource ? 'source' : 'unaffected'
    const status = filtered ? 'Filtered by selection' : isSource ? 'Filter source' : 'Not filtered'
    return todayRailNav ? (
        <Badge
            className="shrink-0 whitespace-nowrap border-current"
            variant={active ? 'info' : 'default'}
            data-bi-filter-status={filterStatus}
        >
            {status}
        </Badge>
    ) : (
        <LemonTag
            className="shrink-0 whitespace-nowrap"
            type={active ? 'info' : 'default'}
            data-bi-filter-status={filterStatus}
        >
            {status}
        </LemonTag>
    )
}
