import {
    getFormattedDate,
    getFormattedTimeInterval,
    getTooltipTitle,
    SeriesDatum,
} from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { IntervalType } from '~/types'

describe('getFormattedDate', () => {
    const paramsToExpectedWithDateString: [string, string][] = [
        ['2024-04-28', '28 Apr 2024'],
        ['2024-05-12', '12 May 2024'],
    ]

    paramsToExpectedWithDateString.forEach(([input, expected]) => {
        it(`expects "${expected}" for date string input "${input}"`, () => {
            expect(getFormattedDate(input)).toEqual(expected)
        })
    })

    const paramsToExpectedWithWrongDateString: [string, string][] = [['this is not a date', 'this is not a date']]

    paramsToExpectedWithWrongDateString.forEach(([input, expected]) => {
        it(`expects "${expected}" for wrong date string "${input}"`, () => {
            expect(getFormattedDate(input)).toEqual(expected)
        })
    })
})

describe('getFormattedTimeInterval', () => {
    const paramsToExpectedWithNumericInput: [number, IntervalType, string][] = [
        [1, 'minute', '1 minute'],
        [2, 'minute', '2 minutes'],
        [1, 'hour', '1 hour'],
        [2, 'hour', '2 hours'],
        [1, 'day', '1 day'],
        [2, 'day', '2 days'],
        [1, 'week', '1 week'],
        [2, 'week', '2 weeks'],
        [1, 'month', '1 month'],
        [2, 'month', '2 months'],
    ]

    paramsToExpectedWithNumericInput.forEach(([input, intervall, expected]) => {
        it(`expects "${expected}" for numeric input "${input}" and intervall "${intervall}"`, () => {
            expect(getFormattedTimeInterval(input, intervall)).toEqual(expected)
        })
    })

    it('expects defaults to input string "i am a string" for wrong string input "i am a string"', () => {
        expect(getFormattedTimeInterval('i am a string' as any, 'day')).toEqual('i am a string')
    })
})

describe('getTooltipTitle', () => {
    const paramsToExpectedWithNumericInput: [
        SeriesDatum[],
        string | ((tooltipData: SeriesDatum[], date: string) => React.ReactNode) | undefined,
        string | number | undefined,
        React.ReactNode | null
    ][] = [
        [[], 'Users', '2024-04-28', 'Users'],
        [[], 'Users', undefined, 'Users'],
        [[], 'Users', 5, 'Users'],
        [[], (_, date) => date, '2024-04-28', '28 Apr 2024'],
        [[], (_, date) => date, undefined, null],
        [[], (_, date) => date, 5, null],
        [[], undefined, '2024-04-28', null],
    ]

    paramsToExpectedWithNumericInput.forEach(([seriesData, altTitleOrFn, date, expected]) => {
        it(`expects "${expected}" for getTooltipTitle for 2nd argument of type "${typeof altTitleOrFn} and 3rd of type "${typeof date}"`, () => {
            expect(getTooltipTitle(seriesData, altTitleOrFn, date)).toEqual(expected)
        })
    })
})
