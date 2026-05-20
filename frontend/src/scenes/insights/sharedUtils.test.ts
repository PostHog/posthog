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
        { in: { teamId: 33, dashboardItemId: Insight123, tabId: 'tab-abc' }, expect: '123/tab-tab-abc' },
        { in: { teamId: 34, dashboardItemId: undefined, tabId: 'tab-xyz' }, expect: 'defaultKey/tab-tab-xyz' },
    ]

    testCases.forEach((testCase) => {
        it(`for ${JSON.stringify(testCase.in)} returns ${JSON.stringify(testCase.expect)}`, () => {
            expect(func(testCase.in)).toEqual(testCase.expect)
        })
    })
})
