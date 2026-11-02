import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { warehouseSyncDashboardSummary } from '~/queries/nodes/DataNode/warehouseSyncWarnings'

import { dashboardLogic } from './dashboardLogic'

export function DashboardWarehouseSyncBanner(): JSX.Element | null {
    const { dashboard, insightTiles } = useValues(dashboardLogic)
    const summary = dashboard ? warehouseSyncDashboardSummary(insightTiles) : null
    if (!dashboard || !summary) {
        return null
    }

    const { sources, insightCount, fingerprint } = summary
    const onlySource = sources.length === 1 ? sources[0] : null
    const origin = onlySource ? onlySource.sourceType : `${sources.length} warehouse sources`

    return (
        <LemonBanner
            type="warning"
            className="mt-4 mb-2"
            data-attr="dashboard-warehouse-sync-warnings"
            // The fingerprint brings a dismissed banner back when another table goes out of date.
            dismissKey={`dashboard-warehouse-sync-${dashboard.id}-${fingerprint}`}
            action={
                onlySource?.sourceId
                    ? {
                          children: 'Manage source',
                          to: urls.dataWarehouseSource(`managed-${onlySource.sourceId}`),
                          targetBlank: true,
                          'data-attr': 'dashboard-warehouse-sync-manage-source',
                      }
                    : undefined
            }
        >
            {`Data from ${origin} is out of date, so ${pluralize(insightCount, 'insight')} on this dashboard may not show current numbers. Hover the Out of date tag on an insight for details.`}
        </LemonBanner>
    )
}
