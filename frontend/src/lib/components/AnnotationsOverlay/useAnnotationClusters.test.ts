import { Dayjs, dayjs } from 'lib/dayjs'

import { AnnotationScope, DatedAnnotationType } from '~/types'

import {
    MIN_BADGE_SPACING_PX,
    PositionedBadge,
    clusterAnnotationBadges,
    getInterpolatedDataPointX,
    tickOverlapsAnyCluster,
} from './useAnnotationClusters'

function makeAnnotation(id: number, date: Dayjs): DatedAnnotationType {
    return {
        id,
        scope: AnnotationScope.Project,
        content: `annotation-${id}`,
        date_marker: date,
        created_at: dayjs(),
        updated_at: dayjs().toISOString(),
        dashboard_item: null,
        deleted: false,
    } as DatedAnnotationType
}

function makeBadge(id: number, leftPx: number, date = dayjs('2022-08-10')): PositionedBadge {
    return {
        dateKey: `key-${id}`,
        date,
        leftPx,
        annotations: [makeAnnotation(id, date)],
    }
}

describe('clusterAnnotationBadges', () => {
    it('returns each badge as its own cluster when all are far apart', () => {
        const badges = [makeBadge(1, 0), makeBadge(2, 100), makeBadge(3, 200)]

        const clusters = clusterAnnotationBadges(badges, MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(3)
        expect(clusters.map((c) => c.leftPx)).toEqual([0, 100, 200])
        expect(clusters.map((c) => c.rightPx)).toEqual([0, 100, 200])
        clusters.forEach((c) => {
            expect(c.annotations).toHaveLength(1)
            expect(c.dateRange[0]).toBe(c.dateRange[1])
        })
    })

    it('merges two overlapping badges into one cluster with combined annotations', () => {
        const dateA = dayjs('2022-08-10')
        const dateB = dayjs('2022-08-11')
        const badgeA = { ...makeBadge(1, 10, dateA) }
        const badgeB = { ...makeBadge(2, 20, dateB) }

        const clusters = clusterAnnotationBadges([badgeA, badgeB], MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(1)
        expect(clusters[0].leftPx).toBe(10)
        expect(clusters[0].rightPx).toBe(20)
        expect(clusters[0].annotations).toHaveLength(2)
        expect(clusters[0].dateRange[0]).toBe(dateA)
        expect(clusters[0].dateRange[1]).toBe(dateB)
    })

    it('chains badges into a single cluster that can span more than minSpacingPx', () => {
        // Badges at 0, 22, 44 px: each within 24 px of the previous, but the cluster
        // spans 44 px total — more than MIN_BADGE_SPACING_PX.
        const badges = [makeBadge(1, 0), makeBadge(2, 22), makeBadge(3, 44)]

        const clusters = clusterAnnotationBadges(badges, MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(1)
        expect(clusters[0].leftPx).toBe(0)
        expect(clusters[0].rightPx).toBe(44)
        expect(clusters[0].annotations).toHaveLength(3)
    })

    it('keeps cluster anchor at leftmost badge position (no jitter as badges merge)', () => {
        const badges = [makeBadge(1, 10), makeBadge(2, 30), makeBadge(3, 50)]

        const clusters = clusterAnnotationBadges(badges, MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(1)
        expect(clusters[0].leftPx).toBe(10)
    })

    it('splits into multiple clusters when a gap exceeds minSpacingPx', () => {
        // 0, 22 merge; then gap of 100 → 122 starts a new cluster; 122, 140 merge.
        const badges = [makeBadge(1, 0), makeBadge(2, 22), makeBadge(3, 122), makeBadge(4, 140)]

        const clusters = clusterAnnotationBadges(badges, MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(2)
        expect(clusters[0].leftPx).toBe(0)
        expect(clusters[0].rightPx).toBe(22)
        expect(clusters[1].leftPx).toBe(122)
        expect(clusters[1].rightPx).toBe(140)
    })

    it('sorts badges by leftPx before clustering (tolerates out-of-order input)', () => {
        const badges = [makeBadge(3, 44), makeBadge(1, 0), makeBadge(2, 22)]

        const clusters = clusterAnnotationBadges(badges, MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(1)
        expect(clusters[0].leftPx).toBe(0)
        expect(clusters[0].rightPx).toBe(44)
    })

    it('returns an empty array for empty input', () => {
        expect(clusterAnnotationBadges([], MIN_BADGE_SPACING_PX)).toEqual([])
    })
})

describe('tickOverlapsAnyCluster', () => {
    it('suppresses a tick that sits at the anchor of a cluster', () => {
        const clusters = clusterAnnotationBadges([makeBadge(1, 100)], MIN_BADGE_SPACING_PX)
        expect(tickOverlapsAnyCluster(100, clusters, MIN_BADGE_SPACING_PX)).toBe(true)
    })

    it('suppresses a tick in the interior of a large chained cluster', () => {
        // Reproducing the bug Greptile flagged: badges at 0, 22, 44 chain into a single
        // cluster anchored at 0. A tick at 56 is only 12 px from the last merged badge,
        // but 56 px from the anchor — must still be suppressed.
        const clusters = clusterAnnotationBadges(
            [makeBadge(1, 0), makeBadge(2, 22), makeBadge(3, 44)],
            MIN_BADGE_SPACING_PX
        )

        expect(tickOverlapsAnyCluster(56, clusters, MIN_BADGE_SPACING_PX)).toBe(true)
    })

    it('does not suppress a tick that is clearly outside any cluster', () => {
        const clusters = clusterAnnotationBadges(
            [makeBadge(1, 0), makeBadge(2, 22), makeBadge(3, 44)],
            MIN_BADGE_SPACING_PX
        )

        // 200 px is well past the rightPx (44) + minSpacing (24) = 68 threshold.
        expect(tickOverlapsAnyCluster(200, clusters, MIN_BADGE_SPACING_PX)).toBe(false)
    })

    it('uses minSpacingPx as an exclusion zone on both sides of the cluster extent', () => {
        const clusters = clusterAnnotationBadges([makeBadge(1, 100)], MIN_BADGE_SPACING_PX)

        // Inside the extension zone on either side.
        expect(tickOverlapsAnyCluster(100 - MIN_BADGE_SPACING_PX, clusters, MIN_BADGE_SPACING_PX)).toBe(true)
        expect(tickOverlapsAnyCluster(100 + MIN_BADGE_SPACING_PX, clusters, MIN_BADGE_SPACING_PX)).toBe(true)
        // Just outside.
        expect(tickOverlapsAnyCluster(100 - MIN_BADGE_SPACING_PX - 1, clusters, MIN_BADGE_SPACING_PX)).toBe(false)
        expect(tickOverlapsAnyCluster(100 + MIN_BADGE_SPACING_PX + 1, clusters, MIN_BADGE_SPACING_PX)).toBe(false)
    })

    it('returns false when there are no clusters', () => {
        expect(tickOverlapsAnyCluster(50, [], MIN_BADGE_SPACING_PX)).toBe(false)
    })
})

describe('getInterpolatedDataPointX', () => {
    it('returns the exact data point x for integer indices', () => {
        const getX = (i: number): number | null => [10, 20, 30][i] ?? null
        expect(getInterpolatedDataPointX(0, getX)).toBe(10)
        expect(getInterpolatedDataPointX(1, getX)).toBe(20)
        expect(getInterpolatedDataPointX(2, getX)).toBe(30)
    })

    it('linearly interpolates between neighboring data points for fractional indices', () => {
        const getX = (i: number): number | null => [0, 100, 200][i] ?? null
        expect(getInterpolatedDataPointX(0.5, getX)).toBe(50)
        expect(getInterpolatedDataPointX(1.25, getX)).toBe(125)
    })

    it('returns null when the floor index is out of range', () => {
        const getX = (i: number): number | null => [10, 20][i] ?? null
        expect(getInterpolatedDataPointX(5, getX)).toBeNull()
    })

    it('falls back to the floor x when the next point is unavailable', () => {
        // Defensive: if Chart.js is mid-render and getDataPointX returns null for floor+1
        // despite a valid floor, we fall back to the floor x rather than throw.
        const getX = (i: number): number | null => (i === 0 ? 10 : null)
        expect(getInterpolatedDataPointX(0.5, getX)).toBe(10)
    })
})
