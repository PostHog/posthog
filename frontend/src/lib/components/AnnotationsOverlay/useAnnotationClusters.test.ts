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
        { name: 'two overlapping badges merge', positions: [10, 20], expected: [[10, 20, 2]] },
        {
            // Regression for the Greptile P2 anchor-only tick suppression bug.
            name: 'chained cluster can span more than minSpacingPx',
            positions: [0, 22, 44],
            expected: [[0, 44, 3]],
        },
        {
            name: 'splits into multiple clusters on a gap',
            positions: [0, 22, 122, 140],
            expected: [
                [0, 22, 2],
                [122, 140, 2],
            ],
        },
    ])('$name', ({ positions, expected }) => {
        const clusters = clusterAnnotationBadges(makeBadges(positions), MIN_BADGE_SPACING_PX)
        expect(clusters.map((c) => [c.leftPx, c.rightPx, c.annotations.length])).toEqual(expected)
    })
})

describe('tickOverlapsAnyCluster', () => {
    const chained = clusterAnnotationBadges(makeBadges([0, 22, 44]), MIN_BADGE_SPACING_PX)

    it('suppresses a tick in the interior of a chained cluster', () => {
        // 56 is 12px from the last badge but 56 from the anchor — must still be suppressed.
        expect(tickOverlapsAnyCluster(56, chained, MIN_BADGE_SPACING_PX)).toBe(true)
    })

    it('does not suppress a tick clearly outside any cluster', () => {
        expect(tickOverlapsAnyCluster(200, chained, MIN_BADGE_SPACING_PX)).toBe(false)
    })
})

describe('getInterpolatedDataPointX', () => {
    const getX = (i: number): number | null => [0, 100, 200][i] ?? null

    it('returns the exact point for integer indices', () => {
        expect(getInterpolatedDataPointX(1, getX)).toBe(100)
    })

    it('linearly interpolates between points for fractional indices', () => {
        expect(getInterpolatedDataPointX(0.5, getX)).toBe(50)
    })
})
