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
        { name: 'merges two overlapping badges', positions: [10, 20], expected: [[10, 20, 2]] },
        {
            // Regression: chained merging lets a cluster span more than minSpacingPx
            // (0→22→44 each within 24 of the previous). The rightPx field must track the
            // full extent so tick suppression sees the interior.
            name: 'chains into a cluster that spans more than minSpacingPx',
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
    // Regression for Greptile P2: the chained cluster at 0,22,44 spans leftPx=0..rightPx=44.
    // A tick at 56 is only 12px from the last badge but 56px from the anchor — previously the
    // anchor-only check let it slip through.
    const chained = clusterAnnotationBadges(makeBadges([0, 22, 44]), MIN_BADGE_SPACING_PX)

    it('suppresses a tick inside a chained cluster (regression)', () => {
        expect(tickOverlapsAnyCluster(56, chained, MIN_BADGE_SPACING_PX)).toBe(true)
    })

    it('does not suppress a tick clearly outside any cluster', () => {
        expect(tickOverlapsAnyCluster(200, chained, MIN_BADGE_SPACING_PX)).toBe(false)
    })
})

describe('getInterpolatedDataPointX', () => {
    const threePoints = (i: number): number | null => [0, 100, 200][i] ?? null

    it('returns the exact point for integer indices', () => {
        expect(getInterpolatedDataPointX(1, threePoints)).toBe(100)
    })

    it('linearly interpolates between neighboring points for fractional indices', () => {
        expect(getInterpolatedDataPointX(0.5, threePoints)).toBe(50)
    })
})
