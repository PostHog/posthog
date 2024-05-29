import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { IntervalType } from '~/types'

describe('getFormattedDate', () => {
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
            expect(getFormattedDate(input, intervall)).toEqual(expected)
        })
    })

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

    it('expects undefined string if no inputs', () => {
        expect(getFormattedDate()).toEqual('undefined')
    })
})
