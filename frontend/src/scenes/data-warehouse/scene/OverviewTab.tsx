import { useActions, useValues } from 'kea'

import { IconDatabase, IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { WarehouseSyncStatusApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { DataWarehouseTab, dataWarehouseSceneLogic } from '../dataWarehouseSceneLogic'
import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'
import { warehouseSyncStatusLogic } from './warehouseSyncStatusLogic'

function formatLag(seconds: number | null): string {
    if (seconds == null) {
        return 'unknown'
    }
    if (seconds < 3600) {
        return `${Math.max(Math.round(seconds / 60), 1)}m`
    }
    if (seconds < 86400) {
        return `${Math.round(seconds / 3600)}h`
    }
    const days = Math.round(seconds / 86400)
    if (days < 365) {
        return `${days}d`
    }
    return `${(days / 365).toFixed(1)}y`
}

function stateBadge(status: WarehouseSyncStatusApi): {
    tagType: 'success' | 'warning' | 'danger' | 'default'
    label: string
} {
    switch (status.state) {
        case 'caught_up':
            return { tagType: 'success', label: 'Up to date' }
        case 'lagging':
            return { tagType: 'warning', label: `${formatLag(status.lag_seconds)} behind` }
        case 'error':
            return { tagType: 'danger', label: 'Sync error' }
        case 'not_started':
        default:
            return { tagType: 'default', label: 'Not started' }
    }
}

function FreshnessHero({ status }: { status: WarehouseSyncStatusApi }): JSX.Element {
    const badge = stateBadge(status)
    return (
        <div className="border rounded p-4">
            <div className="flex items-start justify-between flex-wrap gap-2">
                <div>
                    <div className="text-muted text-xs uppercase tracking-wide">Events up to date through</div>
                    <div className="text-3xl font-bold">
                        {status.fresh_through ? dayjs(status.fresh_through).format('MMM D, YYYY') : '—'}
                    </div>
                    {status.last_activity_at && (
                        <div className="text-muted text-sm mt-1">
                            Last backfilled {dayjs(status.last_activity_at).fromNow()}
                        </div>
                    )}
                </div>
                <LemonTag type={badge.tagType} size="medium">
                    ● {badge.label}
                </LemonTag>
            </div>
        </div>
    )
}

function StatusStrip({ readyAt, host }: { readyAt: string | null; host?: string }): JSX.Element {
    // Region is implied by the connection host subdomain (e.g. *.dw.us.postwh.com); fall back to US.
    const region = host?.match(/\.dw\.([a-z0-9-]+)\./)?.[1]?.toUpperCase() ?? 'US'
    return (
        <div className="border rounded px-4 py-3 flex items-center gap-6 flex-wrap">
            <div className="flex items-center gap-2">
                <IconDatabase className="text-xl text-muted" />
                <span className="font-semibold">Managed warehouse</span>
                <LemonTag type="success">READY</LemonTag>
            </div>
            <div className="text-sm text-muted">
                Region <span className="text-default font-medium">{region}</span>
            </div>
            <div className="text-sm text-muted">
                Deployed{' '}
                <span className="text-default font-medium">
                    {readyAt ? humanFriendlyDetailedTime(readyAt) : 'recently'}
                </span>
            </div>
        </div>
    )
}

function EmptyState(): JSX.Element {
    const { setActiveTab } = useActions(dataWarehouseSceneLogic)
    return (
        <div className="mt-4 border rounded p-8 flex flex-col items-center text-center space-y-3 max-w-160 mx-auto">
            <IconWarning className="text-3xl text-muted" />
            <h2 className="mb-0">No warehouse deployed yet</h2>
            <p className="text-muted mb-0 max-w-120">
                Once you provision a managed warehouse, this page shows how up-to-date your event data is.
            </p>
            <LemonButton type="primary" onClick={() => setActiveTab(DataWarehouseTab.SETTINGS)}>
                Go to settings to provision
            </LemonButton>
        </div>
    )
}

export function OverviewTab(): JSX.Element {
    const { warehouseStatus } = useValues(warehouseProvisioningLogic)
    const { syncStatus, syncStatusLoading } = useValues(warehouseSyncStatusLogic)

    const isReady = warehouseStatus?.state === 'ready'
    if (!isReady) {
        return <EmptyState />
    }

    if (syncStatus === null && syncStatusLoading) {
        return (
            <div className="mt-4 flex justify-center py-8">
                <Spinner />
            </div>
        )
    }

    return (
        <div className="mt-4 space-y-4">
            <StatusStrip readyAt={warehouseStatus?.ready_at ?? null} host={warehouseStatus?.connection?.host} />
            {syncStatus?.error && (
                <LemonBanner type="error">
                    Sync error: {syncStatus.error.message} (since {dayjs(syncStatus.error.since).fromNow()})
                </LemonBanner>
            )}
            {syncStatus && <FreshnessHero status={syncStatus} />}
        </div>
    )
}
