import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { forwardRef, useEffect, useState } from 'react'
import type { HTMLAttributes } from 'react'
import { useInView } from 'react-intersection-observer'

import { InsightVisualizationSkeleton } from 'lib/components/Cards/InsightCard/InsightVisualizationSkeleton'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'

import { type RepeatedTileCopy, repeatedCopiesCollectionKey } from '../dashboardRepeatedGroups'

export interface DashboardRepeatedInsightTileProps extends HTMLAttributes<HTMLDivElement> {
    copy: RepeatedTileCopy
    dashboardId: number | undefined
}

/** One copy of an insight tile in a repeated group. It runs the insight's query with the variable set to one value. */
export const DashboardRepeatedInsightTile = forwardRef<HTMLDivElement, DashboardRepeatedInsightTileProps>(
    function DashboardRepeatedInsightTile({ copy, dashboardId, className, ...divProps }, ref): JSX.Element {
        const { insight, color } = copy.tile
        // A copy runs its query only when it comes near the viewport, and stays mounted after that.
        const { ref: inViewRef, inView } = useInView({ rootMargin: '500px' })
        const [hasBeenInView, setHasBeenInView] = useState(false)
        useEffect(() => {
            if (inView) {
                setHasBeenInView(true)
            }
        }, [inView])
        const mergedRef = useMergeRefs([ref, inViewRef])

        if (!hasBeenInView) {
            return (
                <div {...divProps} ref={mergedRef} className={clsx('InsightCard border', className)}>
                    <InsightVisualizationSkeleton query={insight!.query} />
                </div>
            )
        }
        return (
            <QueryCard
                {...divProps}
                ref={mergedRef}
                className={className}
                query={insight!.query!}
                title={`${copy.value} · ${insight!.name || insight!.derived_name || 'Untitled'}`}
                description={insight!.description}
                ribbonColor={color}
                uniqueKey={copy.key}
                filtersOverride={copy.filters}
                context={{
                    insightProps: {
                        dashboardItemId: `new-AdHoc.${copy.key}`,
                        dataNodeCollectionId: repeatedCopiesCollectionKey(dashboardId ?? 'new'),
                    },
                }}
                data-attr="dashboard-repeated-insight-tile"
            />
        )
    }
)
