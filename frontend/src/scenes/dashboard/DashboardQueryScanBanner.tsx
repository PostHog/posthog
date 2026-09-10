import { useValues } from 'kea'
import { Fragment } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { queryScanDashboardSummary } from '~/queries/nodes/DataNode/queryScan'

import { dashboardLogic } from './dashboardLogic'

export function DashboardQueryScanBanner(): JSX.Element | null {
    const { dashboard, insightTiles, canEditDashboard } = useValues(dashboardLogic)
    const { showQueryScanAdvice } = useValues(uiCustomizationLogic)

    if (!dashboard || !canEditDashboard || !showQueryScanAdvice) {
        return null
    }

    const { entries, signature } = queryScanDashboardSummary(insightTiles)
    if (entries.length === 0) {
        return null
    }

    const single = entries.length === 1
    return (
        <LemonBanner
            type="warning"
            className="mt-4 mb-2"
            dismissKey={`query-scan-dashboard-${dashboard.id}-${signature}`}
        >
            {single
                ? '1 insight on this dashboard reads a large number of events, which can slow down dashboard loads: '
                : `${entries.length} insights on this dashboard read a large number of events, which can slow down dashboard loads: `}
            {entries.map((entry, index) => (
                <Fragment key={entry.tileId}>
                    {index > 0 ? ', ' : ''}
                    <Link to={urls.insightView(entry.shortId)}>{entry.name}</Link>
                </Fragment>
            ))}
            {single ? '. Open it to see the advice.' : '. Open an insight to see the advice.'}
        </LemonBanner>
    )
}
