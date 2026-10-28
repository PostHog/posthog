import { useActions, useValues } from 'kea'

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
    // Page translation replaces bare text nodes, and React then fails to remove or update them.
    // Every text that appears, disappears or changes with a toggle therefore sits in its own element.
    return (
        <LemonBanner type="warning" className="mt-4 mb-2">
            {single
                ? '1 insight on this dashboard reads a large number of events, which can slow down dashboard loads: '
                : `${entries.length} insights on this dashboard read a large number of events, which can slow down dashboard loads: `}
            {visibleEntries.map((entry, index) => (
                <span key={entry.tileId}>
                    {index > 0 ? ', ' : ''}
                    <Link to={urls.insightView(entry.shortId)}>{entry.name}</Link>
                </span>
            ))}
            <span>{single ? '. Open it to see the advice.' : '. Open an insight to see the advice.'}</span>
            {hiddenCount > 0 && (
                <>
                    {' '}
                    <Link onClick={() => setExpanded(!expanded)} data-attr="dashboard-query-scan-banner-toggle">
                        {expanded ? 'Show less' : `Show ${hiddenCount} more`}
                    </Link>
                </>
            )}
        </LemonBanner>
    )
}
