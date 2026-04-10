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

function makeBadges(positions: number[]): PositionedBadge[] {
    const baseDate = dayjs('2022-08-10')
    return positions.map((leftPx, i) => ({
        dateKey: `key-${i}`,
        date: baseDate.add(i, 'day'),
        leftPx,
        annotations: [makeAnnotation(i, baseDate.add(i, 'day'))],
    }))
}

/** [leftPx, rightPx, annotationCount] */
type ExpectedCluster = [number, number, number]

describe('clusterAnnotationBadges', () => {
    it.each<{ name: string; positions: number[]; expected: ExpectedCluster[] }>([
        {
            name: 'each badge is its own cluster when all are far apart',
            positions: [0, 100, 200],
            expected: [
                [0, 0, 1],
                [100, 100, 1],
                [200, 200, 1],
            ],
        },
        {
            name: 'two overlapping badges merge with combined annotations',
            positions: [10, 20],
            expected: [[10, 20, 2]],
        },
        {
            name: 'chained cluster can span more than minSpacingPx',
            positions: [0, 22, 44],
            expected: [[0, 44, 3]],
        },
        {
            name: 'splits on a gap that exceeds minSpacingPx',
            positions: [0, 22, 122, 140],
            expected: [
                [0, 22, 2],
                [122, 140, 2],
            ],
        },
        {
            name: 'sorts unordered input before clustering',
            positions: [44, 0, 22],
            expected: [[0, 44, 3]],
        },
        { name: 'empty input', positions: [], expected: [] },
    ])('$name', ({ positions, expected }) => {
        const clusters = clusterAnnotationBadges(makeBadges(positions), MIN_BADGE_SPACING_PX)

        expect(clusters.map((c) => [c.leftPx, c.rightPx, c.annotations.length])).toEqual(expected)
    })

    it('dateRange tracks earliest and latest dates as a cluster grows', () => {
        const clusters = clusterAnnotationBadges(makeBadges([10, 20, 30]), MIN_BADGE_SPACING_PX)

        expect(clusters).toHaveLength(1)
        const [from, to] = clusters[0].dateRange
        expect(from.isBefore(to)).toBe(true)
        expect(clusters[0].date).toBe(from)
    })
})

describe('tickOverlapsAnyCluster', () => {
    // Chained cluster at 0,22,44 is the regression case: previously, anchor-only checks
    // let ticks inside a chained cluster slip through.
    const chained = clusterAnnotationBadges(makeBadges([0, 22, 44]), MIN_BADGE_SPACING_PX)
    const single = clusterAnnotationBadges(makeBadges([100]), MIN_BADGE_SPACING_PX)

    it.each<{ name: string; clusters: typeof chained; tick: number; expected: boolean }>([
        { name: 'at anchor', clusters: single, tick: 100, expected: true },
        { name: '-minSpacing boundary', clusters: single, tick: 100 - MIN_BADGE_SPACING_PX, expected: true },
        { name: '+minSpacing boundary', clusters: single, tick: 100 + MIN_BADGE_SPACING_PX, expected: true },
        { name: 'just past -minSpacing', clusters: single, tick: 100 - MIN_BADGE_SPACING_PX - 1, expected: false },
        { name: 'just past +minSpacing', clusters: single, tick: 100 + MIN_BADGE_SPACING_PX + 1, expected: false },
        { name: 'interior of chained cluster (regression)', clusters: chained, tick: 56, expected: true },
        { name: 'clearly outside chained cluster', clusters: chained, tick: 200, expected: false },
        { name: 'no clusters', clusters: [], tick: 50, expected: false },
    ])('$name', ({ clusters, tick, expected }) => {
        expect(tickOverlapsAnyCluster(tick, clusters, MIN_BADGE_SPACING_PX)).toBe(expected)
    })
})

describe('getInterpolatedDataPointX', () => {
    const threePoints = (i: number): number | null => [0, 100, 200][i] ?? null
    const floorOnly = (i: number): number | null => (i === 0 ? 10 : null)

    it.each<{ name: string; getX: (i: number) => number | null; index: number; expected: number | null }>([
        { name: 'integer index → exact point', getX: threePoints, index: 0, expected: 0 },
        { name: 'integer index (middle)', getX: threePoints, index: 1, expected: 100 },
        { name: 'integer index (last)', getX: threePoints, index: 2, expected: 200 },
        { name: 'fractional → linear interpolation', getX: threePoints, index: 0.5, expected: 50 },
        { name: 'fractional in second interval', getX: threePoints, index: 1.25, expected: 125 },
        { name: 'out-of-range floor → null', getX: threePoints, index: 5, expected: null },
        { name: 'missing next point falls back to floor', getX: floorOnly, index: 0.5, expected: 10 },
    ])('$name', ({ getX, index, expected }) => {
        expect(getInterpolatedDataPointX(index, getX)).toBe(expected)
    })
})
