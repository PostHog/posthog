import { cleanFilters } from './cleanFilters'
import { ChartDisplayType, InsightType } from '~/types'
import { ShownAsValue } from 'lib/constants'

describe('cleanFilters', () => {
    it('switches display to table if moving from TRENDS to RETENTION', () => {
        expect(
            cleanFilters(
                { insight: InsightType.RETENTION, display: ChartDisplayType.ActionsLineGraphLinear },
                { insight: InsightType.TRENDS, display: ChartDisplayType.ActionsLineGraphLinear }
            )
        ).toEqual(expect.objectContaining({ insight: InsightType.RETENTION, display: ChartDisplayType.ActionsTable }))
    })

    it('removes shownas if moving from stickiness to trends', () => {
        expect(
            cleanFilters(
                { insight: InsightType.TRENDS, shown_as: ShownAsValue.STICKINESS },
                { insight: InsightType.STICKINESS, shown_as: ShownAsValue.STICKINESS }
            )
        ).toEqual(expect.objectContaining({ insight: InsightType.TRENDS, shown_as: undefined }))
    })

    it('removes breakdown when adding breakdowns', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: '$browser', type: 'event' }],
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            { breakdown: '$browser', insight: InsightType.FUNNELS, funnel_viz_type: 'steps' }
        )

        expect(cleanedFilters).toHaveProperty('breakdown', undefined)

        expect(cleanedFilters).toEqual(
            expect.objectContaining({ breakdowns: [{ property: '$browser', type: 'event' }] })
        )
    })

    it('adds breakdown_type when adding breakdown', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdown: '$thing',
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            { insight: InsightType.FUNNELS, funnel_viz_type: 'steps' }
        )

        expect(cleanedFilters).toHaveProperty('breakdown', '$thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
    })

    it('adds breakdown_type when adding breakdowns', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: '$browser', type: 'event' }],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            { insight: InsightType.FUNNELS, funnel_viz_type: 'steps' }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: '$browser', type: 'event' }])
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
    })

    it('removes empty breakdowns array', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [],
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            {
                breakdowns: [{ property: 'something', type: 'event' }],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_type', undefined)
    })

    it('does not include breakdown properties if funnel is not type steps', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: 'any', type: 'event' }],
                breakdown: 'something',
                breakdown_type: 'event',
                breakdown_group_type_index: 1,
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'anything but steps',
            },
            {
                breakdowns: [{ property: 'something', type: 'event' }],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_type', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('removes breakdowns properties when changing away from funnel', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: 'any', type: 'event' }],
                breakdown: 'something',
                breakdown_type: 'event',
                breakdown_group_type_index: 1,
                insight: InsightType.TRENDS,
            },
            {
                breakdowns: [{ property: 'something', type: 'event' }],
                breakdown: 'something',
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'something')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', 1)
    })

    it('cleans breakdown params for Trends', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: 'any', type: 'event' }],
                breakdown: 'something',
                breakdown_type: 'group',
                breakdown_group_type_index: 1,
                insight: InsightType.TRENDS,
            },
            {
                breakdowns: [{ property: 'something', type: 'event' }],
                breakdown: 'one thing',
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'something')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'group')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', 1)
    })
})
