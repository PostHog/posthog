import { useValues } from 'kea'
import { Fragment } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { trimRedundantTail, warehouseSyncDashboardEntries } from '~/queries/nodes/DataNode/warehouseSyncWarnings'

import { dashboardLogic } from './dashboardLogic'

export function DashboardWarehouseSyncBanner(): JSX.Element | null {
    const { dashboard, insightTiles } = useValues(dashboardLogic)
    if (!dashboard) {
        return null
    }

    const entries = warehouseSyncDashboardEntries(insightTiles)
    if (entries.length === 0) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mt-4 mb-2" data-attr="dashboard-warehouse-sync-warnings">
            Some insights on this dashboard read warehouse tables that are out of date, so their results may not be
            current:
            <ul className="list-disc pl-5">
                {entries.map(({ warning, insights }) => (
                    <li
                        key={`${warning.source_id ?? warning.source_type}-${warning.schema_name}-${warning.table_name}`}
                    >
                        <span>{trimRedundantTail(warning.message)}</span> Used by{' '}
                        {insights.map((insight, index) => (
                            <Fragment key={insight.tileId}>
                                {index > 0 ? ', ' : ''}
                                <Link to={urls.insightView(insight.shortId)}>{insight.name}</Link>
                            </Fragment>
                        ))}
                        .
                        {warning.source_id && (
                            <>
                                {' '}
                                <Link to={urls.dataWarehouseSource(`managed-${warning.source_id}`)} target="_blank">
                                    Manage source
                                </Link>
                            </>
                        )}
                    </li>
                ))}
            </ul>
        </LemonBanner>
    )
}
