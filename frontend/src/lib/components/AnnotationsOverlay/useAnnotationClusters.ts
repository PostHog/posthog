import React from 'react'

import { Dayjs } from 'lib/dayjs'

import { DatedAnnotationType } from '~/types'

export const MIN_BADGE_SPACING_PX = 24

export interface AnnotationBadgeCluster {
    date: Dayjs
    dateRange: [Dayjs, Dayjs]
    annotations: DatedAnnotationType[]
    leftPx: number
    /** Rightmost badge absorbed into the cluster. A chained cluster can span more than
     *  minSpacingPx, so callers doing overlap checks need the full extent, not just leftPx. */
    rightPx: number
}

export interface PositionedBadge {
    dateKey: string
    date: Dayjs
    leftPx: number
    annotations: DatedAnnotationType[]
}

export function clusterAnnotationBadges(badges: PositionedBadge[], minSpacingPx: number): AnnotationBadgeCluster[] {
    const sorted = [...badges].sort((a, b) => a.leftPx - b.leftPx)
    const out: AnnotationBadgeCluster[] = []
    for (const badge of sorted) {
        const last = out[out.length - 1]
        if (last && badge.leftPx - last.rightPx < minSpacingPx) {
            last.annotations = [...last.annotations, ...badge.annotations]
            last.dateRange = [last.dateRange[0], badge.date]
            last.rightPx = badge.leftPx
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

export function tickOverlapsAnyCluster(
    tickLeftPx: number,
    clusters: AnnotationBadgeCluster[],
    minSpacingPx: number
): boolean {
    return clusters.some((c) => tickLeftPx >= c.leftPx - minSpacingPx && tickLeftPx <= c.rightPx + minSpacingPx)
}

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

    const clusterByKey = React.useMemo(() => {
        const m = new Map<string, AnnotationBadgeCluster>()
        clusters.forEach((c) => m.set(c.date.toISOString(), c))
        return m
    }, [clusters])

    return { clusters, clusterByKey }
}
