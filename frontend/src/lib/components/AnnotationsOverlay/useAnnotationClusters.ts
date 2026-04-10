import React from 'react'

import { Dayjs } from 'lib/dayjs'

import { DatedAnnotationType } from '~/types'

/**
 * Minimum pixel spacing between annotation badge centers. Annotation groups whose rendered
 * pixel positions fall within this distance are clustered into a single badge so they don't
 * visually overlap. Tuned to roughly the badge diameter plus a bit of breathing room.
 */
export const MIN_BADGE_SPACING_PX = 24

export interface AnnotationBadgeCluster {
    /** Representative date (earliest date in the cluster). Used as the active-state key. */
    date: Dayjs
    /** The earliest and latest actual annotation dates in the cluster — for the popover title. */
    dateRange: [Dayjs, Dayjs]
    /** All annotations from every group merged into this cluster. */
    annotations: DatedAnnotationType[]
    /** Pixel x of the cluster anchor (first/leftmost badge). */
    leftPx: number
    /** Pixel x of the rightmost badge absorbed into the cluster. Equal to `leftPx` for
     *  single-badge clusters. Used for tick-suppression so interior ticks don't leak through
     *  when a cluster has been chained across more than `minSpacingPx`. */
    rightPx: number
}

export interface PositionedBadge {
    dateKey: string
    date: Dayjs
    leftPx: number
    annotations: DatedAnnotationType[]
}

/**
 * Pure clustering pass: merge positioned badges that fall within `minSpacingPx` of the previous
 * badge into a single cluster. Extracted as a plain function so it can be unit-tested in isolation
 * (no React, no Chart.js).
 *
 * The merge criterion is greedy-chained: each badge only needs to be within `minSpacingPx` of the
 * previous badge, so a cluster can span more than `minSpacingPx`. We track `rightPx` explicitly
 * so callers (e.g. tick-suppression) can see the cluster's full horizontal extent.
 */
export function clusterAnnotationBadges(badges: PositionedBadge[], minSpacingPx: number): AnnotationBadgeCluster[] {
    const sorted = [...badges].sort((a, b) => a.leftPx - b.leftPx)
    const out: AnnotationBadgeCluster[] = []
    for (const badge of sorted) {
        const last = out[out.length - 1]
        if (last && badge.leftPx - last.rightPx < minSpacingPx) {
            last.annotations = [...last.annotations, ...badge.annotations]
            last.dateRange = [last.dateRange[0], badge.date]
            last.rightPx = badge.leftPx
            // Keep the first badge's leftPx as the cluster anchor — prevents jitter when
            // additional badges join and keeps the badge visually pinned to a data point.
        } else {
            out.push({
                date: badge.date,
                dateRange: [badge.date, badge.date],
                annotations: badge.annotations,
                leftPx: badge.leftPx,
                rightPx: badge.leftPx,
            })
        }
    }
    return out
}

/** Returns true if a tick at `tickLeftPx` sits within `minSpacingPx` of any cluster's horizontal
 *  extent. Walks the full cluster extent (leftPx..rightPx), not just the anchor, so ticks in the
 *  interior of a large chained cluster are correctly suppressed. */
export function tickOverlapsAnyCluster(
    tickLeftPx: number,
    clusters: AnnotationBadgeCluster[],
    minSpacingPx: number
): boolean {
    return clusters.some((c) => tickLeftPx >= c.leftPx - minSpacingPx && tickLeftPx <= c.rightPx + minSpacingPx)
}

/** Linearly interpolate the pixel x for a fractional data-point index. Returns null when no
 *  neighboring data point is available (chart not ready / index out of range). */
export function getInterpolatedDataPointX(
    dataIndex: number,
    getDataPointX: (index: number) => number | null
): number | null {
    const floor = Math.floor(dataIndex)
    const fraction = dataIndex - floor
    const xFloor = getDataPointX(floor)
    if (xFloor === null) {
        return null
    }
    if (fraction === 0) {
        return xFloor
    }
    const xNext = getDataPointX(floor + 1)
    if (xNext !== null) {
        return xFloor + fraction * (xNext - xFloor)
    }
    return xFloor
}

export interface UseAnnotationClustersArgs {
    annotationBadgeDataIndices: Array<{ dateKey: string; date: Dayjs; dataIndex: number }>
    getDataPointX: (index: number) => number | null
    chartAreaLeft: number
    groupedAnnotations: Record<string, DatedAnnotationType[]>
}

export interface UseAnnotationClustersResult {
    clusters: AnnotationBadgeCluster[]
    clusterByKey: Map<string, AnnotationBadgeCluster>
}

/**
 * Cluster annotation badges whose rendered pixel positions would visually overlap. Each cluster
 * becomes a single badge with a merged annotation list and a date range.
 *
 * Kept out of the kea logic because `getDataPointX` reads live from the Chart.js instance via a
 * hook — it can't be threaded into a selector. The interesting business logic
 * (`clusterAnnotationBadges`) is a pure function exported for direct unit testing.
 */
export function useAnnotationClusters({
    annotationBadgeDataIndices,
    getDataPointX,
    chartAreaLeft,
    groupedAnnotations,
}: UseAnnotationClustersArgs): UseAnnotationClustersResult {
    const clusters = React.useMemo<AnnotationBadgeCluster[]>(() => {
        const positioned: PositionedBadge[] = annotationBadgeDataIndices
            .map(({ dateKey, date, dataIndex }) => {
                const absoluteX = getInterpolatedDataPointX(dataIndex, getDataPointX)
                if (absoluteX === null) {
                    return null
                }
                return {
                    dateKey,
                    date,
                    leftPx: absoluteX - chartAreaLeft,
                    annotations: groupedAnnotations[dateKey] || [],
                }
            })
            .filter((b): b is PositionedBadge => b !== null)

        return clusterAnnotationBadges(positioned, MIN_BADGE_SPACING_PX)
    }, [annotationBadgeDataIndices, getDataPointX, chartAreaLeft, groupedAnnotations])

    // Map: cluster key (representative date ISO string) → cluster. Used by the popover to
    // look up its annotations and date range from the active badge.
    const clusterByKey = React.useMemo(() => {
        const m = new Map<string, AnnotationBadgeCluster>()
        clusters.forEach((c) => m.set(c.date.toISOString(), c))
        return m
    }, [clusters])

    return { clusters, clusterByKey }
}
