import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { IntervalType } from '~/types'

describe('getFormattedDate', () => {
    const paramsToExpected: [number, IntervalType, string][] = [
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

    paramsToExpected.forEach(([input, intervall, expected]) => {
        it(`expect "${expected}" for numeric input "${input}" and intervall "${intervall}"`, () => {
            expect(getFormattedDate(input, intervall)).toEqual(expected)
        })
    })
})
