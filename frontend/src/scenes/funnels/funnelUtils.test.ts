import { dayjs } from 'lib/dayjs'

import { EventsNode } from '~/queries/schema/schema-general'
import {
    FunnelConversionWindowTimeUnit,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
} from '~/types'

import {
    EMPTY_BREAKDOWN_VALUES,
    getBreakdownStepValues,
    getClampedFunnelStepRange,
    getIncompleteConversionWindowStartDate,
    getMeanAndStandardDeviation,
    getVisibilityKey,
    parseDisplayNameForCorrelation,
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
