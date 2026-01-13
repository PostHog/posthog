import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightShortId } from '~/types'

const Insight123 = '123' as InsightShortId

describe('keyForInsightLogicProps', () => {
    const func = keyForInsightLogicProps('defaultKey')

    it('throws if no dashboardItemId', () => {
        expect(() => {
            func({})
        }).toThrow('Must init with dashboardItemId, even if undefined')
    })

    const testCases = [
        { in: { teamId: 33, dashboardItemId: Insight123 }, expect: '123' },
        { in: { teamId: 34, dashboardItemId: undefined }, expect: 'defaultKey' },
        { in: { teamId: 35, dashboardItemId: Insight123, dashboardId: 456 }, expect: '123/on-dashboard-456' },
        { in: { teamId: 36, dashboardItemId: 'new', dashboardId: 456 }, expect: 'new' },
        {
            in: { teamId: 37, dashboardItemId: 'new-AdHoc.xyz' as InsightShortId, dashboardId: 456 },
            expect: 'new-AdHoc.xyz',
        },
    ]

    testCases.forEach((testCase) => {
        it(`for ${JSON.stringify(testCase.in)} returns ${JSON.stringify(testCase.expect)}`, () => {
            expect(func(testCase.in)).toEqual(testCase.expect)
        })
    })
})
