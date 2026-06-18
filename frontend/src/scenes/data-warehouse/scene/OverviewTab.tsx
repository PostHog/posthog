import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconDatabase, IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { DataWarehouseTab, dataWarehouseSceneLogic } from '../dataWarehouseSceneLogic'
import { WarehouseSyncStatus, formatLag, formatRows, getMockWarehouseSyncStatus } from './mockWarehouseSyncStatus'
import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'

function stateBadge(status: WarehouseSyncStatus): {
    tagType: 'success' | 'warning' | 'danger' | 'default'
    label: string
} {
    switch (status.state) {
        case 'caught_up':
            return { tagType: 'success', label: 'Up to date' }
        case 'lagging':
            return { tagType: 'warning', label: `${formatLag(status.lagSeconds)} behind` }
        case 'seeding':
            return { tagType: 'warning', label: 'Backfilling…' }
        case 'error':
            return { tagType: 'danger', label: 'Sync error' }
        case 'not_started':
        default:
            return { tagType: 'default', label: 'Not started' }
    }
}

function HeroStat({ label, value, sublabel }: { label: string; value: string; sublabel?: string }): JSX.Element {
    return (
        <div>
            <div className="text-muted text-xs uppercase tracking-wide">{label}</div>
            <div className="text-xl font-semibold">{value}</div>
            {sublabel && <div className="text-muted text-xs">{sublabel}</div>}
        </div>
    )
}

function FreshnessHero({ status }: { status: WarehouseSyncStatus }): JSX.Element {
    const badge = stateBadge(status)
    return (
        <div className="border rounded p-4 space-y-4">
            <div className="flex items-start justify-between flex-wrap gap-2">
                <div>
                    <div className="text-muted text-xs uppercase tracking-wide">Events up to date through</div>
                    <div className="text-3xl font-bold">
                        {status.freshThrough ? dayjs(status.freshThrough).format('MMM D, YYYY') : '—'}
                    </div>
                    {status.lastActivityAt && (
                        <div className="text-muted text-sm mt-1">
                            Last updated {dayjs(status.lastActivityAt).fromNow()}
                        </div>
                    )}
                </div>
                <LemonTag type={badge.tagType} size="medium">
                    ● {badge.label}
                </LemonTag>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 pt-2">
                <HeroStat
                    label="Initial backfill"
                    value={
                        status.initialBackfill.complete
                            ? 'Complete'
                            : status.initialBackfill.progressPct != null
                              ? `${status.initialBackfill.progressPct}%`
                              : 'In progress'
                    }
                    sublabel="historical events"
                />
                <HeroStat label="Events synced" value={formatRows(status.totalRowsSynced)} sublabel="rows replicated" />
                <HeroStat
                    label="Last update"
                    value={status.lastActivityAt ? dayjs(status.lastActivityAt).fromNow() : '—'}
                    sublabel="most recent sync"
                />
            </div>
        </div>
    )
}

function LoadProgressBar({ status }: { status: WarehouseSyncStatus }): JSX.Element {
    const pct = status.initialBackfill.complete ? 100 : (status.initialBackfill.progressPct ?? 0)
    const complete = status.initialBackfill.complete

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted">
                <span>Historical events</span>
                <span>Live</span>
            </div>
            <Tooltip title={complete ? 'Backfill complete — keeping up in real time' : `${pct}% backfilled`}>
                <div className="relative h-3 w-full rounded-full bg-border overflow-hidden">
                    <div
                        className="absolute inset-y-0 left-0 bg-success rounded-full"
                        // Width is data-driven, so it can't be a static utility class.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${pct}%` }}
                    />
                    <div className="absolute inset-y-0 right-0 w-1 bg-warning animate-pulse" />
                </div>
            </Tooltip>
            <div className="text-xs text-muted">
                {complete ? 'Backfill complete — keeping up in real time' : `${pct}% of historical events backfilled`}
            </div>
        </div>
    )
}

function StatusStrip({ readyAt, host }: { readyAt: string | null; host?: string }): JSX.Element {
    // Region is implied by the connection host subdomain (e.g. *.dw.us.postwh.com); fall back to a mock.
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
                Once you provision a managed warehouse, this page shows a live overview of your deployment and how
                up-to-date your event data is.
            </p>
            <LemonButton type="primary" onClick={() => setActiveTab(DataWarehouseTab.SETTINGS)}>
                Go to settings to provision
            </LemonButton>
        </div>
    )
}

export function OverviewTab(): JSX.Element {
    const { warehouseStatus } = useValues(warehouseProvisioningLogic)
    const status = useMemo(() => getMockWarehouseSyncStatus(), [])

    const isReady = warehouseStatus?.state === 'ready'
    if (!isReady) {
        return <EmptyState />
    }

    return (
        <div className="mt-4 space-y-4">
            <StatusStrip readyAt={warehouseStatus?.ready_at ?? null} host={warehouseStatus?.connection?.host} />
            {status.error && (
                <LemonBanner type="error">
                    Sync error: {status.error.message} (since {dayjs(status.error.since).fromNow()})
                </LemonBanner>
            )}
            <FreshnessHero status={status} />
            <LoadProgressBar status={status} />
        </div>
    )
}
