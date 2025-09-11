import clsx from 'clsx'

import { Query } from '~/queries/Query/Query'

import { EmbeddedAnalyticsTile, EmbeddedQueryTile } from './common'

export const EmbeddedTiles = (props: { tiles: EmbeddedAnalyticsTile[] }): JSX.Element => {
    const { tiles } = props

    return (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-x-4 gap-y-8">
            {tiles.map((tile, i) => {
                if (tile.kind === 'query') {
                    return <EmbeddedQueryTileItem key={i} tile={tile} />
                }
                return null
            })}
        </div>
    )
}

const EmbeddedQueryTileItem = ({ tile }: { tile: EmbeddedQueryTile }): JSX.Element => {
    const { query, title, layout } = tile

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-6',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? 'xxl:order-12',
                layout.className
            )}
        >
            {title && (
                <div className="flex flex-row items-center mb-3">
                    <h2>{title}</h2>
                </div>
            )}

            <Query
                key={`${tile.tileId}-${query.kind === 'DataVisualizationNode' ? JSON.stringify(query.chartSettings?.seriesBreakdownColumn) : 'no-breakdown'}`}
                query={query}
                readOnly={true}
            />
        </div>
    )
}
