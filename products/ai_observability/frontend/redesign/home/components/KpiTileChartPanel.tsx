import { IconX } from '@posthog/icons'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { dateFilterToText } from 'lib/utils/dateFilters'

import type { TraceMetricBucketSizeApi, TraceMetricTileApi } from '../../../generated/api.schemas'
import { formatTileDetail, formatTileValue, tileSlug } from '../formatTile'
import { KpiTileChart } from './KpiTileChart'

export interface KpiTileChartPanelProps {
    tile: TraceMetricTileApi
    bucketStarts: string[]
    bucketSize: TraceMetricBucketSizeApi
    dateFrom: string
    dateTo: string | null
    timezone: string
    /** The list the tile links to, if any. */
    activityUrl?: string
    insightUrl: string
    onClose: () => void
}

export function KpiTileChartPanel({
    tile,
    bucketStarts,
    bucketSize,
    dateFrom,
    dateTo,
    timezone,
    activityUrl,
    insightUrl,
    onClose,
}: KpiTileChartPanelProps): JSX.Element {
    const slug = tileSlug(tile.key)
    const range = dateFilterToText(dateFrom, dateTo, null)
    const detail = formatTileDetail(tile)
    return (
        // pinned: data-attrs feed autocapture; dashboards and tests find the panel and its controls by these values
        <LemonCard hoverEffect={false} className="flex min-w-0 flex-col gap-2 p-3" data-attr={`home-chart-${slug}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-xs font-medium text-secondary">
                        {range ? `${tile.label} · ${range}` : tile.label}
                    </span>
                    <span className="text-lg font-semibold tabular-nums" translate="no">
                        {formatTileValue(tile.key, tile.value)}
                    </span>
                    {detail ? <span className="text-xs text-secondary">{detail}</span> : null}
                </div>
                <div className="flex items-center gap-3">
                    {activityUrl ? (
                        <Link to={activityUrl} className="text-xs" data-attr={`home-chart-${slug}-activity`}>
                            View in Activity
                        </Link>
                    ) : null}
                    <Link to={insightUrl} className="text-xs" data-attr={`home-chart-${slug}-insight`}>
                        Open as insight
                    </Link>
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={onClose}
                        tooltip="Close chart"
                        data-attr={`home-chart-${slug}-close`}
                    />
                </div>
            </div>
            <div className="relative flex h-48 flex-col">
                <KpiTileChart
                    metricKey={tile.key}
                    label={tile.label}
                    series={tile.series}
                    bucketStarts={bucketStarts}
                    bucketSize={bucketSize}
                    timezone={timezone}
                />
            </div>
        </LemonCard>
    )
}
