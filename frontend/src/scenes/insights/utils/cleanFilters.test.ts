import { cleanFilters } from './cleanFilters'
import {
    ChartDisplayType,
    ChartDisplayTypesThatDoNotShowValuesOnSeries,
    FilterType,
    FunnelsFilterType,
    FunnelStepReference,
    FunnelVizType,
    InsightType,
    TrendsFilterType,
} from '~/types'
import { FEATURE_FLAGS, ShownAsValue } from 'lib/constants'

describe('cleanFilters', () => {
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
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType,
            {
                breakdown: '$browser',
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType
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
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
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
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: '$browser', type: 'event' }])
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
    })

    it('defaults to normalizing URL for breakdowns by $current_url', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: '$current_url', type: 'event' }],
                breakdown_type: 'event',
            } as TrendsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', true)
    })

    it('defaults to normalizing URL for breakdown by $current_url', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdown: '$current_url',
                breakdown_type: 'event',
            } as TrendsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', true)
    })

    it('defaults to normalizing URL for breakdowns by $pathname', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: '$pathname', type: 'event' }],
                breakdown_type: 'event',
            } as TrendsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', true)
    })

    it('defaults to normalizing URL for breakdown by $pathname', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdown: '$pathname',
                breakdown_type: 'event',
            } as TrendsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', true)
    })

    it('can set normalizing URL for breakdown to false', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdown: '$current_url',
                breakdown_type: 'event',
                breakdown_normalize_url: false,
            } as TrendsFilterType,
            { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps } as FunnelsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', false)
    })

    it('removes normalizing URL for breakdown by other properties', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: '$pageview', type: 'event' }],
                breakdown_type: 'event',
            } as TrendsFilterType,
            {
                breakdowns: [{ property: '$pathname', type: 'event', normalize_url: true }],
                breakdown_type: 'event',
            } as TrendsFilterType
        )

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', undefined)
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
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType,
            {
                breakdowns: [{ property: 'something', type: 'event' }],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType
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
                funnel_viz_type: FunnelVizType.Trends,
            } as FunnelsFilterType,
            {
                breakdowns: [{ property: 'something', type: 'event' }],
                breakdown_type: 'event',
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType
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
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType
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
                funnel_viz_type: FunnelVizType.Steps,
            } as FunnelsFilterType,
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
                funnel_viz_type: FunnelVizType.Steps,
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
                funnel_viz_type: FunnelVizType.Steps,
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

    it('reads "smoothing_intervals" and "interval" from URL when viewing and corrects bad pairings', () => {
        const cleanedFilters = cleanFilters(
            {
                interval: 'day',
                smoothing_intervals: 4,
            },
            {
                interval: 'day',
                smoothing_intervals: 3,
            }
        )

        expect(cleanedFilters).toHaveProperty('smoothing_intervals', 1)
    })

    it('can add funnel step reference', () => {
        const cleanedFilters = cleanFilters(
            {
                funnel_step_reference: FunnelStepReference.previous,
                insight: InsightType.FUNNELS,
            },
            {}
        )

        expect(cleanedFilters).toHaveProperty('funnel_step_reference', FunnelStepReference.previous)
    })

    it('removes the interval from funnels', () => {
        const cleanedFilters = cleanFilters(
            {
                insight: InsightType.FUNNELS,
                interval: 'hour',
            },
            {}
        )

        expect(cleanedFilters).toHaveProperty('interval', undefined)
    })

    it('keeps the interval for trends funnels', () => {
        const cleanedFilters = cleanFilters(
            {
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Trends,
                interval: 'hour',
            },
            {}
        )

        expect(cleanedFilters).toHaveProperty('interval', 'hour')
    })

    describe('show_values_on_series', () => {
        ;[InsightType.TRENDS, InsightType.LIFECYCLE, InsightType.STICKINESS].forEach((insight) => {
            it(`keeps show values on series for ${insight}`, () => {
                const cleanedFilters = cleanFilters(
                    {
                        insight,
                        show_values_on_series: true,
                    },
                    {}
                )

                expect(cleanedFilters).toHaveProperty('show_values_on_series', true)
            })
        })
        ChartDisplayTypesThatDoNotShowValuesOnSeries.forEach((display) => {
            it(`removes show values on series for ${display}`, () => {
                const cleanedFilters = cleanFilters(
                    {
                        insight: InsightType.TRENDS,
                        display,
                        show_values_on_series: true,
                    },
                    {}
                )

                expect(cleanedFilters).not.toHaveProperty('show_values_on_series')
            })
        })
        ;[(InsightType.PATHS, InsightType.FUNNELS, InsightType.RETENTION)].forEach((insight) => {
            it(`removes show values on series for ${insight}`, () => {
                const cleanedFilters = cleanFilters(
                    {
                        insight,
                        show_values_on_series: true,
                    },
                    {}
                )

                expect(cleanedFilters).not.toHaveProperty('show_values_on_series')
            })
        })
        it('sets show values on series for piecharts if it is undefined', () => {
            const cleanedFilters = cleanFilters(
                {
                    insight: InsightType.TRENDS,
                    display: ChartDisplayType.ActionsPie,
                },
                {}
            )

            expect(cleanedFilters).toHaveProperty('show_values_on_series', true)
        })
        it('can set show values on series for piecharts to false', () => {
            const cleanedFilters = cleanFilters(
                {
                    insight: InsightType.TRENDS,
                    display: ChartDisplayType.ActionsPie,
                    show_values_on_series: false,
                },
                {}
            )

            expect(cleanedFilters).toHaveProperty('show_values_on_series', false)
        })
    })
})
