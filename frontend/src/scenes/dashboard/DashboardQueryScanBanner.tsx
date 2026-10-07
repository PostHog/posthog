import { useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { QueryScanDashboardEntry, queryScanDashboardEntries } from '~/queries/nodes/DataNode/queryScan'

import { dashboardLogic } from './dashboardLogic'

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

    // Keyed by dashboard so that moving to another dashboard collapses the list again.
    return <QueryScanBannerContent key={dashboard.id} entries={entries} />
}

function QueryScanBannerContent({ entries }: { entries: QueryScanDashboardEntry[] }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

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
            {hiddenCount > 0 && (
                <>
                    <span>{expanded ? ' (' : ' and '}</span>
                    <Link onClick={() => setExpanded(!expanded)} data-attr="dashboard-query-scan-banner-toggle">
                        {expanded ? 'show less' : `${hiddenCount} more`}
                    </Link>
                    <span>{expanded ? ')' : ''}</span>
                </>
            )}
            <span>{single ? '. Open it to see the advice.' : '. Open an insight to see the advice.'}</span>
        </LemonBanner>
    )
}
