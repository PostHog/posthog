import { IconTrending } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, type LemonTagType, Link } from '@posthog/lemon-ui'

import { TraceMetricChangeToneApi, TraceMetricStatusApi, type TraceMetricTileApi } from '../../../generated/api.schemas'
import { formatTileChange, formatTileValue, tileSlug } from '../formatTile'
import { KpiTileSparkline } from './KpiTileSparkline'

export interface KpiTileProps {
    /** Null while the metrics load. */
    tile: TraceMetricTileApi | null
    to?: string
    chartOpen?: boolean
    /** Shows the chart button on a tile that is set up. */
    onToggleChart?: () => void
}

const TONE_TAG: Record<TraceMetricChangeToneApi, LemonTagType> = {
    [TraceMetricChangeToneApi.Good]: 'success',
    [TraceMetricChangeToneApi.Bad]: 'danger',
    [TraceMetricChangeToneApi.Neutral]: 'muted',
}

const TILE_CLASS = 'flex min-w-0 flex-col gap-1 rounded border bg-surface-primary p-3'

function TileBody({ tile, slug }: { tile: TraceMetricTileApi; slug: string }): JSX.Element {
    if (tile.status === TraceMetricStatusApi.NotSetUp) {
        return (
            <>
                <span className="text-base font-semibold text-secondary">Not set up</span>
                {tile.docsUrl && tile.setupLabel ? (
                    // pinned: data-attrs feed autocapture; dashboards and tests find the setup link by this value
                    <Link
                        to={tile.docsUrl}
                        target="_blank"
                        className="text-xs"
                        data-attr={`home-tile-${slug}-not-set-up`}
                    >
                        {tile.setupLabel}
                    </Link>
                ) : null}
            </>
        )
    }
    return (
        <>
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <span className="whitespace-nowrap text-2xl font-semibold tabular-nums" translate="no">
                    {formatTileValue(tile.key, tile.value)}
                </span>
                {tile.change !== null ? (
                    <LemonTag type={TONE_TAG[tile.changeTone]} size="small" className="tabular-nums" translate="no">
                        {formatTileChange(tile.change, tile.changeUnit)}
                    </LemonTag>
                ) : null}
            </div>
            <div className="h-8">{tile.series.length > 0 ? <KpiTileSparkline series={tile.series} /> : null}</div>
        </>
    )
}

export function KpiTile({ tile, to, chartOpen = false, onToggleChart }: KpiTileProps): JSX.Element {
    if (tile === null) {
        return (
            <div className={TILE_CLASS}>
                <LemonSkeleton className="h-4 w-1/2" />
                <LemonSkeleton className="h-7 w-2/3" />
                <LemonSkeleton className="h-8 w-full" />
            </div>
        )
    }
    const slug = tileSlug(tile.key)
    return (
        // pinned: data-attrs feed autocapture; dashboards and tests find the tile by this value
        <div className={TILE_CLASS} data-attr={`home-tile-${slug}`}>
            <div className="flex min-w-0 items-center justify-between gap-1">
                {to ? (
                    <Link to={to} subtle className="truncate text-xs font-medium text-secondary">
                        {tile.label}
                    </Link>
                ) : (
                    <span className="truncate text-xs font-medium text-secondary">{tile.label}</span>
                )}
                {onToggleChart && tile.status === TraceMetricStatusApi.Ok ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconTrending />}
                        active={chartOpen}
                        onClick={onToggleChart}
                        tooltip={chartOpen ? 'Hide chart' : 'Show chart'}
                        aria-label={`${tile.label} chart`}
                        aria-pressed={chartOpen}
                        // pinned: data-attrs feed autocapture; dashboards and tests find the chart button by this value
                        data-attr={`home-chart-${slug}-toggle`}
                    />
                ) : null}
            </div>
            <TileBody tile={tile} slug={slug} />
        </div>
    )
}
