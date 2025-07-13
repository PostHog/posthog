import { NON_VALUES_ON_SERIES_DISPLAY_TYPES, ShownAsValue } from 'lib/constants'

import {
    ChartDisplayType,
    FilterType,
    FunnelStepReference,
    FunnelVizType,
    FunnelsFilterType,
    InsightType,
    TrendsFilterType,
} from '~/types'

import { cleanFilters } from './cleanFilters'

describe('cleanFilters', () => {
    it('removes shownas from trends insights', () => {
        expect(cleanFilters({ insight: InsightType.TRENDS, shown_as: ShownAsValue.STICKINESS })).toEqual(
            expect.objectContaining({ insight: InsightType.TRENDS, shown_as: undefined })
        )
    })

    it('removes breakdown when it also has breakdowns', () => {
        const cleanedFilters = cleanFilters({
            breakdown: '$browser',
            breakdowns: [{ property: '$browser', type: 'event' }],
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
        } as FunnelsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown', undefined)

        expect(cleanedFilters).toEqual(
            expect.objectContaining({ breakdowns: [{ property: '$browser', type: 'event' }] })
        )
    })

    it('allows breakdown_type with breakdown', () => {
        const cleanedFilters = cleanFilters({
            breakdown: '$thing',
            breakdown_type: 'event',
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
        } as FunnelsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown', '$thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
    })

    it('allows breakdown_type when adding breakdowns', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: '$browser', type: 'event' }],
            breakdown_type: 'event',
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
        } as FunnelsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: '$browser', type: 'event' }])
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
    })

    it('defaults to normalizing URL for breakdowns by $current_url', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: '$current_url', type: 'event' }],
            breakdown_type: 'event',
        } as TrendsFilterType)

        expect(cleanedFilters).toMatchObject({
            breakdowns: [
                {
                    property: '$current_url',
                    type: 'event',
                    normalize_url: true,
                },
            ],
        })
    })

    it('defaults to normalizing URL for breakdown by $current_url', () => {
        const cleanedFilters = cleanFilters({
            breakdown: '$current_url',
            breakdown_type: 'event',
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', true)
    })

    it('defaults to normalizing URL for breakdowns by $pathname', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: '$pathname', type: 'event' }],
            breakdown_type: 'event',
        } as TrendsFilterType)

        expect(cleanedFilters).toMatchObject({
            breakdowns: [
                {
                    property: '$pathname',
                    type: 'event',
                    normalize_url: true,
                },
            ],
        })
    })

    it('defaults to normalizing URL for breakdown by $pathname', () => {
        const cleanedFilters = cleanFilters({
            breakdown: '$pathname',
            breakdown_type: 'event',
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', true)
    })

    it('can set normalizing URL for breakdown to false', () => {
        const cleanedFilters = cleanFilters({
            breakdown: '$current_url',
            breakdown_type: 'event',
            breakdown_normalize_url: false,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown_normalize_url', false)
    })

    it('removes normalizing URL for breakdown by other properties', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: '$pageview', type: 'event' }],
            breakdown_type: 'event',
        } as TrendsFilterType)

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
        const cleanedFilters = cleanFilters({
            breakdowns: [],
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
        } as FunnelsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_type', undefined)
    })

    it('does not include breakdown properties if funnel is time to convert', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: 'any', type: 'event' }],
            breakdown: 'something',
            breakdown_type: 'event',
            breakdown_group_type_index: 1,
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.TimeToConvert,
        } as FunnelsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_type', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('keeps multiple breakdowns', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: 'any', type: 'event' }],
            insight: InsightType.TRENDS,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: 'any', type: 'event' }])
    })

    it('keeps normalize_url for multiple breakdowns', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: '$current_url', type: 'event', normalize_url: true }],
            insight: InsightType.TRENDS,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', [
            { property: '$current_url', type: 'event', normalize_url: true },
        ])

        cleanedFilters.breakdowns![0].normalize_url = false
        expect(cleanedFilters).toHaveProperty('breakdowns', [
            { property: '$current_url', type: 'event', normalize_url: false },
        ])
    })

    it('restores a breakdown type for legacy multiple breakdowns', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: 'any' }],
            breakdown_type: 'event',
            insight: InsightType.TRENDS,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: 'any', type: 'event' }])
        expect(cleanedFilters.breakdown_type).toBeUndefined()
    })

    it('cleans a breakdown when multiple breakdowns are used', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [{ property: 'any', type: 'event' }],
            breakdown_type: 'event',
            breakdown: 'test',
            insight: InsightType.TRENDS,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', [{ property: 'any', type: 'event' }])
        expect(cleanedFilters).toHaveProperty('breakdown_type', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', undefined)
    })

    it('uses a breakdown when multiple breakdowns are empty', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [],
            breakdown_type: 'event',
            breakdown: 'test',
            insight: InsightType.TRENDS,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown', 'test')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
    })

    it('keeps a breakdown limit', () => {
        const cleanedFilters = cleanFilters({
            breakdown_limit: 22,
            insight: InsightType.TRENDS,
        } as TrendsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdown_limit', 22)
    })

    it('keeps single property filters for trends', () => {
        const cleanedFilters = cleanFilters({
            breakdown: 'one thing',
            breakdown_type: 'event',
            insight: InsightType.TRENDS,
        })

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'one thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('keeps single property filters for funnels', () => {
        const cleanedFilters = cleanFilters({
            breakdown: 'one thing',
            breakdown_type: 'event',
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
        } as FunnelsFilterType)

        expect(cleanedFilters).toHaveProperty('breakdowns', undefined)
        expect(cleanedFilters).toHaveProperty('breakdown', 'one thing')
        expect(cleanedFilters).toHaveProperty('breakdown_type', 'event')
        expect(cleanedFilters).toHaveProperty('breakdown_group_type_index', undefined)
    })

    it('keeps a multi property breakdown for trends', () => {
        const cleanedFilters = cleanFilters({
            breakdowns: [
                { property: 'one thing', type: 'event' },
                { property: 'two thing', type: 'event' },
            ],
            breakdown_type: 'event',
            insight: InsightType.TRENDS,
        })

        expect(cleanedFilters).toHaveProperty('breakdowns', [
            { property: 'one thing', type: 'event' },
            { property: 'two thing', type: 'event' },
        ])
        expect(cleanedFilters.breakdown_type).toBeUndefined()
    })

    it('reads "smoothing_intervals" and "interval" from URL when viewing and corrects bad pairings', () => {
        const cleanedFilters = cleanFilters({
            interval: 'day',
            smoothing_intervals: 4,
        })

        expect(cleanedFilters).toHaveProperty('smoothing_intervals', 1)
    })

    it('can add funnel step reference', () => {
        const cleanedFilters = cleanFilters({
            funnel_step_reference: FunnelStepReference.previous,
            insight: InsightType.FUNNELS,
        })

        expect(cleanedFilters).toHaveProperty('funnel_step_reference', FunnelStepReference.previous)
    })

    it('removes the interval from funnels', () => {
        const cleanedFilters = cleanFilters({
            insight: InsightType.FUNNELS,
            interval: 'hour',
        })

        expect(cleanedFilters).toHaveProperty('interval', undefined)
    })

    it('keeps the interval for trends funnels', () => {
        const cleanedFilters = cleanFilters({
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Trends,
            interval: 'hour',
        })

        expect(cleanedFilters).toHaveProperty('interval', 'hour')
    })

    describe('show_values_on_series', () => {
        ;[InsightType.TRENDS, InsightType.LIFECYCLE, InsightType.STICKINESS].forEach((insight) => {
            it(`keeps show values on series for ${insight}`, () => {
                const cleanedFilters = cleanFilters({
                    insight,
                    show_values_on_series: true,
                })

                expect(cleanedFilters).toHaveProperty('show_values_on_series', true)
            })
        })
        NON_VALUES_ON_SERIES_DISPLAY_TYPES.forEach((display) => {
            it(`removes show values on series for ${display}`, () => {
                const cleanedFilters = cleanFilters({
                    insight: InsightType.TRENDS,
                    display,
                    show_values_on_series: true,
                })

                expect(cleanedFilters).not.toHaveProperty('show_values_on_series')
            })
        })
        ;[(InsightType.PATHS, InsightType.FUNNELS, InsightType.RETENTION)].forEach((insight) => {
            it(`removes show values on series for ${insight}`, () => {
                const cleanedFilters = cleanFilters({
                    insight,
                    show_values_on_series: true,
                })

                expect(cleanedFilters).not.toHaveProperty('show_values_on_series')
            })
        })
        it('sets show values on series for piecharts if it is undefined', () => {
            const cleanedFilters = cleanFilters({
                insight: InsightType.TRENDS,
                display: ChartDisplayType.ActionsPie,
            })

            expect(cleanedFilters).toHaveProperty('show_values_on_series', true)
        })
        it('can set show values on series for piecharts to false', () => {
            const cleanedFilters = cleanFilters({
                insight: InsightType.TRENDS,
                display: ChartDisplayType.ActionsPie,
                show_values_on_series: false,
            })

            expect(cleanedFilters).toHaveProperty('show_values_on_series', false)
        })
    })
})
