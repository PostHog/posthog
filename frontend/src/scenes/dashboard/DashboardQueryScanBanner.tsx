import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { QueryScanDashboardEntry, queryScanDashboardEntries } from '~/queries/nodes/DataNode/queryScan'

import { dashboardLogic } from './dashboardLogic'
import { dashboardQueryScanBannerLogic } from './dashboardQueryScanBannerLogic'

const COLLAPSED_ENTRY_COUNT = 3

export function DashboardQueryScanBanner(): JSX.Element | null {
    const { dashboard, insightTiles, canEditDashboard } = useValues(dashboardLogic)
    if (!dashboard || !canEditDashboard) {
        return null
    }

    const entries = queryScanDashboardEntries(insightTiles)
    if (entries.length === 0) {
        return null
    }

    return <QueryScanBannerContent dashboardId={dashboard.id} entries={entries} />
}

function QueryScanBannerContent({
    dashboardId,
    entries,
}: {
    dashboardId: number
    entries: QueryScanDashboardEntry[]
}): JSX.Element {
    const logic = dashboardQueryScanBannerLogic({ dashboardId })
    const { expanded } = useValues(logic)
    const { setExpanded } = useActions(logic)

    const single = entries.length === 1
    const hiddenCount = Math.max(entries.length - COLLAPSED_ENTRY_COUNT, 0)
    const visibleEntries = expanded ? entries : entries.slice(0, COLLAPSED_ENTRY_COUNT)
    return (
        <LemonBanner type="warning" className="mt-4 mb-2">
            {single
                ? '1 insight on this dashboard reads a large number of events, which can slow down dashboard loads: '
                : `${entries.length} insights on this dashboard read a large number of events, which can slow down dashboard loads: `}
            {visibleEntries.map((entry, index) => (
                <Fragment key={entry.tileId}>
                    {index > 0 ? ', ' : ''}
                    <Link to={urls.insightView(entry.shortId)}>{entry.name}</Link>
                </Fragment>
            ))}
            {/* Wrapped in a span so that page translation, which replaces text nodes, cannot leave stale text behind. */}
            {hiddenCount > 0 && !expanded && (
                <span>
                    {' and '}
                    <Link onClick={() => setExpanded(true)} data-attr="dashboard-query-scan-banner-toggle">
                        {`${hiddenCount} more`}
                    </Link>
                </span>
            )}
            {single ? '. Open it to see the advice.' : '. Open an insight to see the advice.'}
            {hiddenCount > 0 && expanded && (
                <span>
                    {' '}
                    <Link onClick={() => setExpanded(false)} data-attr="dashboard-query-scan-banner-toggle">
                        Show less
                    </Link>
                </span>
            )}
        </LemonBanner>
    )
}
