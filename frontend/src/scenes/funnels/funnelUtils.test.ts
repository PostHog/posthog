import { dayjs } from 'lib/dayjs'

import { EventsNode } from '~/queries/schema/schema-general'
import {
    FunnelConversionWindowTimeUnit,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
    FunnelStep,
    FunnelStepReference,
    FunnelStepWithNestedBreakdown,
} from '~/types'

import {
    aggregateBreakdownResult,
    EMPTY_BREAKDOWN_VALUES,
    getBreakdownStepValues,
    getClampedFunnelStepRange,
    getIncompleteConversionWindowStartDate,
    getLastFilledStep,
    getMeanAndStandardDeviation,
    getReferenceStep,
    getVisibilityKey,
    parseDisplayNameForCorrelation,
    stepsWithConversionMetrics,
} from './funnelUtils'

describe('getMeanAndStandardDeviation', () => {
    const arrayToExpectedValues: [number[], number[]][] = [
        [
            [1, 2, 3, 4, 5],
            [3, Math.sqrt(2)],
        ],
        [
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            [5.5, Math.sqrt(8.25)],
        ],
        [[1], [1, 0]],
        [[], [0, 100]],
        [
            [1, 1, 1, 1, 1],
            [1, 0],
        ],
        [
            [1, 1, 1, 1, 5],
            [1.8, 1.6],
        ],
    ]

    arrayToExpectedValues.forEach(([array, expected]) => {
        it(`expect mean and deviation for array=${array} to equal ${expected}`, () => {
            const [mean, stdDev] = getMeanAndStandardDeviation(array)
            expect(mean).toBeCloseTo(expected[0])
            expect(stdDev).toBeCloseTo(expected[1])
        })
    })
})

describe('getBreakdownStepValues()', () => {
    it('is baseline breakdown', () => {
        expect(getBreakdownStepValues({ breakdown: 'blah', breakdown_value: 'Blah' }, 21, true)).toStrictEqual({
            rowKey: 'baseline_0',
            breakdown: ['baseline'],
            breakdown_value: ['Baseline'],
        })
    })
    it('breakdowns are well formed arrays', () => {
        expect(
            getBreakdownStepValues({ breakdown: ['blah', 'woof'], breakdown_value: ['Blah', 'Woof'] }, 21)
        ).toStrictEqual({
            rowKey: 'blah_woof_21',
            breakdown: ['blah', 'woof'],
            breakdown_value: ['Blah', 'Woof'],
        })
    })
    it('breakdowns are empty arrays', () => {
        expect(getBreakdownStepValues({ breakdown: [], breakdown_value: [] }, 21)).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdowns are arrays with empty string', () => {
        expect(getBreakdownStepValues({ breakdown: [''], breakdown_value: [''] }, 21)).toStrictEqual(
            EMPTY_BREAKDOWN_VALUES
        )
    })
    it('breakdowns are arrays with null', () => {
        expect(
            getBreakdownStepValues(
                {
                    breakdown: [null as unknown as string | number],
                    breakdown_value: [null as unknown as string | number],
                },
                21
            )
        ).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdowns are arrays with undefined', () => {
        expect(
            getBreakdownStepValues(
                {
                    breakdown: [undefined as unknown as string | number],
                    breakdown_value: [undefined as unknown as string | number],
                },
                21
            )
        ).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdown is string', () => {
        expect(getBreakdownStepValues({ breakdown: 'blah', breakdown_value: 'Blah' }, 21)).toStrictEqual({
            rowKey: 'blah_21',
            breakdown: ['blah'],
            breakdown_value: ['Blah'],
        })
    })
    it('breakdown is empty string', () => {
        expect(getBreakdownStepValues({ breakdown: '', breakdown_value: '' }, 21)).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdown is undefined string', () => {
        expect(getBreakdownStepValues({ breakdown: undefined, breakdown_value: undefined }, 21)).toStrictEqual(
            EMPTY_BREAKDOWN_VALUES
        )
    })
    it('breakdown is null string', () => {
        expect(getBreakdownStepValues({ breakdown: null, breakdown_value: null }, 21)).toStrictEqual(
            EMPTY_BREAKDOWN_VALUES
        )
    })
})

describe('getVisibilityKey()', () => {
    it('returns string representation for breakdown', () => {
        expect(getVisibilityKey(undefined)).toEqual('(empty string)')
        expect(getVisibilityKey(null)).toEqual('(empty string)')
        expect(getVisibilityKey('a')).toEqual('a')
        expect(getVisibilityKey(['a', 'b'])).toEqual('a::b')
        expect(getVisibilityKey(1)).toEqual('1')
        expect(getVisibilityKey([1, 2])).toEqual('1::2')
    })
})

describe('getIncompleteConversionWindowStartDate()', () => {
    const windows = [
        {
            funnelWindowInterval: 10,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Second,
            expected: '2018-04-04T15:59:50.000Z',
        },
        {
            funnelWindowInterval: 60,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Minute,
            expected: '2018-04-04T15:00:00.000Z',
        },
        {
            funnelWindowInterval: 24,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Hour,
            expected: '2018-04-03T16:00:00.000Z',
        },
        {
            funnelWindowInterval: 7,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
            expected: '2018-03-28T16:00:00.000Z',
        },
        {
            funnelWindowInterval: 53,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Week,
            expected: '2017-03-29T16:00:00.000Z',
        },
        {
            funnelWindowInterval: 12,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Month,
            expected: '2017-04-04T16:00:00.000Z',
        },
    ]
    const frozenStartDate = dayjs('2018-04-04T16:00:00.000Z')

    windows.forEach(({ expected, ...w }) => {
        it(`get start date of conversion window ${w.funnelWindowInterval} ${w.funnelWindowIntervalUnit}s`, () => {
            expect(getIncompleteConversionWindowStartDate(w, frozenStartDate).toISOString()).toEqual(expected)
        })
    })
})

describe('getClampedFunnelStepRange', () => {
    const series = [{}, {}, {}] as EventsNode[]

    it('does not set funnelFromStep or funnelToStep', () => {
        expect(getClampedFunnelStepRange({}, series)).toEqual({})
    })

    it('does not touch valid funnelFromStep', () => {
        expect(getClampedFunnelStepRange({ funnelFromStep: 0 }, series)).toEqual({ funnelFromStep: 0 })
    })

    it('does not touch valid funnelToStep', () => {
        expect(getClampedFunnelStepRange({ funnelToStep: 2 }, series)).toEqual({ funnelToStep: 2 })
    })

    it('does not touch valid funnelFromStep and funnelToStep', () => {
        expect(getClampedFunnelStepRange({ funnelFromStep: 0, funnelToStep: 2 }, series)).toEqual({
            funnelFromStep: 0,
            funnelToStep: 2,
        })
    })

    it('minimum for funnelFromStep is 0', () => {
        expect(getClampedFunnelStepRange({ funnelFromStep: -2 }, series)).toEqual({ funnelFromStep: 0 })
    })

    it('maximum for funnelFromStep is 1', () => {
        expect(getClampedFunnelStepRange({ funnelFromStep: 4 }, series)).toEqual({ funnelFromStep: 1 })
    })

    it('minimum for funnelToStep is 1', () => {
        expect(getClampedFunnelStepRange({ funnelToStep: -2 }, series)).toEqual({ funnelToStep: 1 })
    })

    it('maximum for funnelToStep is 2', () => {
        expect(getClampedFunnelStepRange({ funnelToStep: 4 }, series)).toEqual({ funnelToStep: 2 })
    })
})

describe('parseEventAndProperty', () => {
    const basicFunnelRecord: FunnelCorrelation = {
        event: { event: '$pageview::bzzz', properties: {}, elements: [] },
        odds_ratio: 1,
        correlation_type: FunnelCorrelationType.Success,
        success_count: 1,
        failure_count: 1,
        success_people_url: '/some/people/url',
        failure_people_url: '/some/people/url',
        result_type: FunnelCorrelationResultsType.Events,
    }
    it('chooses the correct name based on Event type', async () => {
        const result = parseDisplayNameForCorrelation(basicFunnelRecord)
        expect(result).toEqual({
            first_value: '$pageview::bzzz',
            second_value: undefined,
        })
    })

    it('chooses the correct name based on Property type', async () => {
        const result = parseDisplayNameForCorrelation({
            ...basicFunnelRecord,
            result_type: FunnelCorrelationResultsType.Properties,
        })
        expect(result).toEqual({
            first_value: '$pageview',
            second_value: 'bzzz',
        })
    })

    it('chooses the correct name based on EventWithProperty type', async () => {
        const result = parseDisplayNameForCorrelation({
            ...basicFunnelRecord,
            result_type: FunnelCorrelationResultsType.EventWithProperties,
            event: {
                event: '$pageview::library::1.2',
                properties: { random: 'x' },
                elements: [],
            },
        })
        expect(result).toEqual({
            first_value: 'library',
            second_value: '1.2',
        })
    })

    it('handles autocapture events on EventWithProperty type', async () => {
        const result = parseDisplayNameForCorrelation({
            ...basicFunnelRecord,
            result_type: FunnelCorrelationResultsType.EventWithProperties,
            event: {
                event: '$autocapture::elements_chain::xyz_elements_a.link*',
                properties: { $event_type: 'click' },
                elements: [
                    {
                        tag_name: 'a',
                        href: '#',
                        attributes: { blah: 'https://example.com' },
                        nth_child: 0,
                        nth_of_type: 0,
                        order: 0,
                        text: 'bazinga',
                    },
                ],
            },
        })
        expect(result).toEqual({
            first_value: 'clicked link with text "bazinga"',
            second_value: undefined,
        })
    })

    it('handles autocapture events without elements_chain on EventWithProperty type', async () => {
        const result = parseDisplayNameForCorrelation({
            ...basicFunnelRecord,
            result_type: FunnelCorrelationResultsType.EventWithProperties,
            event: {
                event: '$autocapture::library::1.2',
                properties: { random: 'x' },
                elements: [],
            },
        })
        expect(result).toEqual({
            first_value: 'library',
            second_value: '1.2',
        })
    })
})

// Helpers for building minimal FunnelStep fixtures
const makeStep = (overrides: Partial<FunnelStep> & { count: number; order: number }): FunnelStep => ({
    action_id: 'step',
    name: `Step ${overrides.order}`,
    type: 'events',
    average_conversion_time: null,
    median_conversion_time: null,
    people: [],
    converted_people_url: '',
    dropped_people_url: '',
    breakdown: overrides.breakdown ?? 'all',
    breakdown_value: overrides.breakdown_value ?? 'all',
    ...overrides,
})

describe('aggregateBreakdownResult', () => {
    it('returns empty array for empty results', () => {
        expect(aggregateBreakdownResult([])).toEqual([])
    })

    it('single breakdown series returns steps with nested_breakdown populated', () => {
        const series: FunnelStep[][] = [
            [
                makeStep({ count: 100, order: 0, breakdown: 'Chrome', breakdown_value: 'Chrome' }),
                makeStep({ count: 50, order: 1, breakdown: 'Chrome', breakdown_value: 'Chrome' }),
            ],
        ]
        const result = aggregateBreakdownResult(series, 'browser')

        expect(result).toHaveLength(2)
        expect(result[0].count).toBe(100)
        expect(result[1].count).toBe(50)
        expect(result[0].breakdown).toBe('browser')
        expect(result[0].nested_breakdown).toHaveLength(1)
        expect(result[0].nested_breakdown![0].breakdown_value).toBe('Chrome')
    })

    it('multiple breakdown series sums counts and orders by first step count descending', () => {
        const series: FunnelStep[][] = [
            [
                makeStep({ count: 30, order: 0, breakdown: 'Firefox', breakdown_value: 'Firefox' }),
                makeStep({ count: 10, order: 1, breakdown: 'Firefox', breakdown_value: 'Firefox' }),
            ],
            [
                makeStep({ count: 70, order: 0, breakdown: 'Chrome', breakdown_value: 'Chrome' }),
                makeStep({ count: 40, order: 1, breakdown: 'Chrome', breakdown_value: 'Chrome' }),
            ],
        ]
        const result = aggregateBreakdownResult(series, 'browser')

        expect(result[0].count).toBe(100) // 30 + 70
        expect(result[1].count).toBe(50) // 10 + 40
        // nested_breakdown ordered by first step count descending: Chrome (70) before Firefox (30)
        expect(result[0].nested_breakdown![0].breakdown_value).toBe('Chrome')
        expect(result[0].nested_breakdown![1].breakdown_value).toBe('Firefox')
    })

    describe('average_conversion_time weighted average', () => {
        it.each([
            {
                scenario: 'all null → result is null',
                series: [
                    [
                        makeStep({ count: 50, order: 0, breakdown: 'A', breakdown_value: 'A' }),
                        makeStep({
                            count: 30,
                            order: 1,
                            breakdown: 'A',
                            breakdown_value: 'A',
                            average_conversion_time: null,
                        }),
                    ],
                    [
                        makeStep({ count: 50, order: 0, breakdown: 'B', breakdown_value: 'B' }),
                        makeStep({
                            count: 20,
                            order: 1,
                            breakdown: 'B',
                            breakdown_value: 'B',
                            average_conversion_time: null,
                        }),
                    ],
                ],
                expectedTime: null,
            },
            {
                scenario: 'mix of null and non-null → only non-null contribute',
                series: [
                    [
                        makeStep({ count: 50, order: 0, breakdown: 'A', breakdown_value: 'A' }),
                        makeStep({
                            count: 40,
                            order: 1,
                            breakdown: 'A',
                            breakdown_value: 'A',
                            average_conversion_time: 10,
                        }),
                    ],
                    [
                        makeStep({ count: 50, order: 0, breakdown: 'B', breakdown_value: 'B' }),
                        makeStep({
                            count: 20,
                            order: 1,
                            breakdown: 'B',
                            breakdown_value: 'B',
                            average_conversion_time: null,
                        }),
                    ],
                ],
                // Only A contributes: (10*40) / 40 = 10
                expectedTime: 10,
            },
            {
                scenario: 'all non-null with different counts → weighted calculation',
                series: [
                    [
                        makeStep({ count: 50, order: 0, breakdown: 'A', breakdown_value: 'A' }),
                        makeStep({
                            count: 30,
                            order: 1,
                            breakdown: 'A',
                            breakdown_value: 'A',
                            average_conversion_time: 60,
                        }),
                    ],
                    [
                        makeStep({ count: 50, order: 0, breakdown: 'B', breakdown_value: 'B' }),
                        makeStep({
                            count: 70,
                            order: 1,
                            breakdown: 'B',
                            breakdown_value: 'B',
                            average_conversion_time: 20,
                        }),
                    ],
                ],
                // (60*30 + 20*70) / (30+70) = (1800 + 1400) / 100 = 32
                expectedTime: 32,
            },
        ])('$scenario', ({ series, expectedTime }) => {
            const result = aggregateBreakdownResult(series, 'browser')
            // Step 0 has no conversion time to aggregate meaningfully; check step 1
            expect(result[1].average_conversion_time).toBe(expectedTime)
        })
    })

    it('median_conversion_time is always null', () => {
        const series: FunnelStep[][] = [
            [
                makeStep({ count: 100, order: 0, breakdown: 'A', breakdown_value: 'A' }),
                makeStep({
                    count: 50,
                    order: 1,
                    breakdown: 'A',
                    breakdown_value: 'A',
                    median_conversion_time: 15,
                }),
            ],
        ]
        const result = aggregateBreakdownResult(series, 'browser')
        expect(result[1].median_conversion_time).toBeNull()
    })
})

describe('stepsWithConversionMetrics', () => {
    const makeNestedStep = (
        overrides: Partial<FunnelStepWithNestedBreakdown> & { count: number; order: number }
    ): FunnelStepWithNestedBreakdown => ({
        ...makeStep(overrides),
        ...overrides,
    })

    it('basic 3-step funnel with FunnelStepReference.total', () => {
        const steps = [
            makeNestedStep({ count: 100, order: 0 }),
            makeNestedStep({ count: 60, order: 1 }),
            makeNestedStep({ count: 30, order: 2 }),
        ]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.total)

        expect(result[0].conversionRates.fromBasisStep).toBe(1) // 100/100
        expect(result[1].conversionRates.fromBasisStep).toBe(0.6) // 60/100 (total)
        expect(result[2].conversionRates.fromBasisStep).toBe(0.3) // 30/100 (total)
        expect(result[1].conversionRates.total).toBe(0.6)
        expect(result[2].conversionRates.total).toBe(0.3)
    })

    it('basic 3-step funnel with FunnelStepReference.previous', () => {
        const steps = [
            makeNestedStep({ count: 100, order: 0 }),
            makeNestedStep({ count: 60, order: 1 }),
            makeNestedStep({ count: 30, order: 2 }),
        ]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.previous)

        expect(result[0].conversionRates.fromBasisStep).toBe(1) // first step always total
        expect(result[1].conversionRates.fromBasisStep).toBe(0.6) // 60/100 (fromPrevious)
        expect(result[2].conversionRates.fromBasisStep).toBe(0.5) // 30/60 (fromPrevious)
        expect(result[1].conversionRates.fromPrevious).toBe(0.6)
        expect(result[2].conversionRates.fromPrevious).toBe(0.5)
    })

    it('zero count at step 0 (empty funnel) → total is 0, not NaN', () => {
        const steps = [makeNestedStep({ count: 0, order: 0 }), makeNestedStep({ count: 0, order: 1 })]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.total)

        expect(result[0].conversionRates.total).toBe(0)
        expect(result[1].conversionRates.total).toBe(0)
        expect(Number.isNaN(result[0].conversionRates.total)).toBe(false)
        expect(Number.isNaN(result[1].conversionRates.total)).toBe(false)
    })

    it('zero count at intermediate step → fromPrevious is 0 for next step', () => {
        const steps = [
            makeNestedStep({ count: 100, order: 0 }),
            makeNestedStep({ count: 0, order: 1 }),
            makeNestedStep({ count: 0, order: 2 }),
        ]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.previous)

        expect(result[2].conversionRates.fromPrevious).toBe(0)
    })

    it('with optionalSteps — droppedOffFromPrevious references last non-optional step', () => {
        const steps = [
            makeNestedStep({ count: 100, order: 0 }),
            makeNestedStep({ count: 80, order: 1 }),
            makeNestedStep({ count: 50, order: 2 }), // optional (1-indexed: 3)
            makeNestedStep({ count: 40, order: 3 }),
        ]
        // optionalSteps is 1-indexed, so step index 2 = optional step 3
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.previous, [3])

        // Step 3 (index 3) should use step 1 (index 1, last non-optional) as previous, not step 2 (optional)
        expect(result[3].droppedOffFromPrevious).toBe(80 - 40) // 80 (step 1) - 40 (step 3)
        expect(result[3].conversionRates.fromPrevious).toBe(40 / 80)
    })

    it('with nested_breakdown — computes per-breakdown conversion rates', () => {
        const steps: FunnelStepWithNestedBreakdown[] = [
            makeNestedStep({
                count: 200,
                order: 0,
                nested_breakdown: [
                    makeStep({ count: 120, order: 0, breakdown: 'Chrome', breakdown_value: 'Chrome' }),
                    makeStep({ count: 80, order: 0, breakdown: 'Firefox', breakdown_value: 'Firefox' }),
                ],
            }),
            makeNestedStep({
                count: 100,
                order: 1,
                nested_breakdown: [
                    makeStep({ count: 90, order: 1, breakdown: 'Chrome', breakdown_value: 'Chrome' }),
                    makeStep({ count: 10, order: 1, breakdown: 'Firefox', breakdown_value: 'Firefox' }),
                ],
            }),
        ]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.total)

        // Chrome: 90/120 total
        expect(result[1].nested_breakdown![0].conversionRates.total).toBe(90 / 120)
        expect(result[1].nested_breakdown![0].conversionRates.fromPrevious).toBe(90 / 120)
        // Firefox: 10/80 total
        expect(result[1].nested_breakdown![1].conversionRates.total).toBe(10 / 80)
    })

    it('nested breakdowns with outlier detection — divergent breakdown gets significant: true', () => {
        // Create 5 breakdowns where one is an outlier
        const breakdownCounts = [
            { step0: 100, step1: 50 }, // 50% conversion
            { step0: 100, step1: 48 }, // 48%
            { step0: 100, step1: 52 }, // 52%
            { step0: 100, step1: 49 }, // 49%
            { step0: 100, step1: 5 }, // 5% — outlier
        ]
        const steps: FunnelStepWithNestedBreakdown[] = [
            makeNestedStep({
                count: 500,
                order: 0,
                nested_breakdown: breakdownCounts.map((b, i) =>
                    makeStep({
                        count: b.step0,
                        order: 0,
                        breakdown: `bd${i}`,
                        breakdown_value: `bd${i}`,
                    })
                ),
            }),
            makeNestedStep({
                count: 204,
                order: 1,
                nested_breakdown: breakdownCounts.map((b, i) =>
                    makeStep({
                        count: b.step1,
                        order: 1,
                        breakdown: `bd${i}`,
                        breakdown_value: `bd${i}`,
                    })
                ),
            }),
        ]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.total)

        // The outlier breakdown (index 4, 5% conversion) should be flagged as significant
        expect(result[1].nested_breakdown![4].significant!.total).toBe(true)
        // Normal breakdowns should not be significant
        expect(result[1].nested_breakdown![0].significant!.total).toBe(false)
    })

    it('droppedOffFromPrevious is never negative', () => {
        const steps = [
            makeNestedStep({ count: 50, order: 0 }),
            makeNestedStep({ count: 100, order: 1 }), // count > previous (can happen with sampling)
        ]
        const result = stepsWithConversionMetrics(steps, FunnelStepReference.total)

        expect(result[1].droppedOffFromPrevious).toBe(0) // Math.max(50 - 100, 0)
    })
})

describe('getReferenceStep', () => {
    const steps = ['a', 'b', 'c']

    it.each([
        { scenario: 'index=0 → returns steps[0]', index: 0, ref: FunnelStepReference.total, expected: 'a' },
        {
            scenario: 'index=undefined → returns steps[0]',
            index: undefined,
            ref: FunnelStepReference.total,
            expected: 'a',
        },
        {
            scenario: 'previous with index=2 → returns steps[1]',
            index: 2,
            ref: FunnelStepReference.previous,
            expected: 'b',
        },
        {
            scenario: 'previous with index=1 → returns steps[0]',
            index: 1,
            ref: FunnelStepReference.previous,
            expected: 'a',
        },
        { scenario: 'total with index=2 → returns steps[0]', index: 2, ref: FunnelStepReference.total, expected: 'a' },
    ])('$scenario', ({ index, ref, expected }) => {
        expect(getReferenceStep(steps, ref, index)).toBe(expected)
    })
})

describe('getLastFilledStep', () => {
    it.each([
        {
            scenario: 'all steps have count > 0 → returns step at index',
            steps: [
                makeStep({ count: 10, order: 0 }),
                makeStep({ count: 5, order: 1 }),
                makeStep({ count: 3, order: 2 }),
            ],
            index: 1,
            expectedOrder: 1,
        },
        {
            scenario: 'all steps have count > 0, no index → returns last step',
            steps: [
                makeStep({ count: 10, order: 0 }),
                makeStep({ count: 5, order: 1 }),
                makeStep({ count: 3, order: 2 }),
            ],
            index: undefined,
            expectedOrder: 2,
        },
        {
            scenario: 'last step has count: 0 → returns last step with count > 0',
            steps: [
                makeStep({ count: 10, order: 0 }),
                makeStep({ count: 5, order: 1 }),
                makeStep({ count: 0, order: 2 }),
            ],
            index: undefined,
            expectedOrder: 1,
        },
        {
            scenario: 'all steps have count: 0 → returns steps[0]',
            steps: [
                makeStep({ count: 0, order: 0 }),
                makeStep({ count: 0, order: 1 }),
                makeStep({ count: 0, order: 2 }),
            ],
            index: undefined,
            expectedOrder: 0,
        },
    ])('$scenario', ({ steps, index, expectedOrder }) => {
        expect(getLastFilledStep(steps, index).order).toBe(expectedOrder)
    })
})
