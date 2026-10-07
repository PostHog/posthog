import { useValues } from 'kea'
import { Fragment, useState } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { queryScanDashboardEntries } from '~/queries/nodes/DataNode/queryScan'

import { dashboardLogic } from './dashboardLogic'

const COLLAPSED_ENTRY_COUNT = 3

export function DashboardQueryScanBanner(): JSX.Element | null {
    const { dashboard, insightTiles, canEditDashboard } = useValues(dashboardLogic)
    const [expanded, setExpanded] = useState(false)
    if (!dashboard || !canEditDashboard) {
        return null
    }

    const entries = queryScanDashboardEntries(insightTiles)
    if (entries.length === 0) {
        return null
    }

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
            {hiddenCount > 0 && !expanded && (
                <>
                    {' and '}
                    <Link onClick={() => setExpanded(true)} data-attr="dashboard-query-scan-banner-toggle">
                        {`${hiddenCount} more`}
                    </Link>
                </>
            )}
            {single ? '. Open it to see the advice.' : '. Open an insight to see the advice.'}
            {hiddenCount > 0 && expanded && (
                <>
                    {' '}
                    <Link onClick={() => setExpanded(false)} data-attr="dashboard-query-scan-banner-toggle">
                        Show less
                    </Link>
                </>
            )}
        </LemonBanner>
    )
}
