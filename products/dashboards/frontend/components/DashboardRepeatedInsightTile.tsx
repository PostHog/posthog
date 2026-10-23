import { forwardRef } from 'react'
import type { HTMLAttributes } from 'react'

import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'

import type { RepeatedTileCopy } from '../dashboardRepeatedGroups'

export interface DashboardRepeatedInsightTileProps extends HTMLAttributes<HTMLDivElement> {
    copy: RepeatedTileCopy
}

/** One copy of an insight tile in a repeated group. It runs the insight's query with the variable set to one value. */
export const DashboardRepeatedInsightTile = forwardRef<HTMLDivElement, DashboardRepeatedInsightTileProps>(
    function DashboardRepeatedInsightTile({ copy, ...divProps }, ref): JSX.Element {
        const { insight, color } = copy.tile
        return (
            <QueryCard
                {...divProps}
                ref={ref}
                query={insight!.query!}
                title={`${copy.value} · ${insight!.name || insight!.derived_name || 'Untitled'}`}
                description={insight!.description}
                ribbonColor={color}
                uniqueKey={copy.key}
                filtersOverride={copy.filters}
                data-attr="dashboard-repeated-insight-tile"
            />
        )
    }
)
