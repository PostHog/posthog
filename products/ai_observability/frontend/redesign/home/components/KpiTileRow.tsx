import type { TraceMetricKeyApi, TraceMetricsApi } from '../../../generated/api.schemas'
import { KpiTile } from './KpiTile'

export interface KpiTileRowProps {
    metrics: TraceMetricsApi | null
    loading: boolean
    links: Partial<Record<TraceMetricKeyApi, string>>
    openChartKey: TraceMetricKeyApi | null
    onToggleChart: (key: TraceMetricKeyApi) => void
}

const LOADING_TILE_COUNT = 6

function TileGrid({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-2 gap-2 @2xl:grid-cols-3 @5xl:grid-cols-6">{children}</div>
        </div>
    )
}

export function KpiTileRow({
    metrics,
    loading,
    links,
    openChartKey,
    onToggleChart,
}: KpiTileRowProps): JSX.Element | null {
    if (loading) {
        return (
            <TileGrid>
                {Array.from({ length: LOADING_TILE_COUNT }, (_, index) => (
                    <KpiTile key={index} tile={null} />
                ))}
            </TileGrid>
        )
    }
    if (metrics === null) {
        return null
    }
    return (
        <TileGrid>
            {metrics.tiles.map((tile) => (
                <KpiTile
                    key={tile.key}
                    tile={tile}
                    to={links[tile.key]}
                    chartOpen={tile.key === openChartKey}
                    onToggleChart={() => onToggleChart(tile.key)}
                />
            ))}
        </TileGrid>
    )
}
