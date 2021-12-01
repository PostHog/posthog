import { cleanFilters } from './cleanFilters'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import { FEATURE_FLAGS, ShownAsValue } from 'lib/constants'

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

    const breakdownIndexTestCases = [
        {
            filters: { breakdown_type: 'group', breakdown_group_type_index: 0, insight: InsightType.TRENDS },
            expected: 0,
        },
        {
            filters: { breakdown_type: 'group', breakdown_group_type_index: 3, insight: InsightType.TRENDS },
            expected: 3,
        },
        {
            filters: { breakdown_type: 'group', breakdown_group_type_index: null, insight: InsightType.TRENDS },
            expected: undefined,
        },
        {
            filters: { breakdown_type: 'group', breakdown_group_type_index: undefined, insight: InsightType.TRENDS },
            expected: undefined,
        },
        {
            filters: { breakdown_type: 'event', breakdown_group_type_index: 0, insight: InsightType.TRENDS },
            expected: undefined,
        },
    ]
    breakdownIndexTestCases.forEach((testCase) => {
        it(`can add a breakdown_group_type_index of ${testCase.filters.breakdown_group_type_index} when breakdown type is ${testCase.filters.breakdown_type}`, () => {
            const cleanedFilters = cleanFilters(testCase.filters as Partial<FilterType>)
            expect(cleanedFilters.breakdown_group_type_index).toEqual(testCase.expected)
        })
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

    it('keeps single property filters switching to trends', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdown: 'one thing',
                breakdown_type: 'event',
                insight: InsightType.TRENDS,
            },
            {
                breakdown: 'one thing',
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'one thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('keeps single property filters when switching to funnels', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdown: 'one thing',
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            {
                breakdown: 'one thing',
                breakdown_type: 'event',
                insight: InsightType.TRENDS,
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'one thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('keeps the first multi property filter when switching to trends', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [
                    { property: 'one thing', type: 'event' },
                    { property: 'two thing', type: 'event' },
                ],
                breakdown_type: 'event',
                insight: InsightType.TRENDS,
            },
            {
                breakdowns: [
                    { property: 'one thing', type: 'event' },
                    { property: 'two thing', type: 'event' },
                ],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            }
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'one thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('adds the first multi property filter when switching from trends', () => {
        const featureFlags = {}
        featureFlags[`${FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES}`] = true

        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: 'one thing', type: 'event' }],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            {
                breakdown: 'one thing',
                breakdown_type: 'event',
                insight: InsightType.TRENDS,
            },
            featureFlags
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: 'one thing', type: 'event' }])
        expect(cleanedFilters).toHaveProperty('breakdown', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })
})
