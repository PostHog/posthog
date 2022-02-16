import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightShortId } from '~/types'

const Insight123 = '123' as InsightShortId

describe('keyForInsightLogicProps', () => {
    const func = keyForInsightLogicProps('defaultKey', 'sceneKey')

    it('throws if no dashboardItemId', () => {
        expect(() => {
            func({})
        }).toThrow('Must init with dashboardItemId, even if undefined')
    })

    const testCases = [
        { in: { teamId: 31, syncWithUrl: true, dashboardItemId: Insight123 }, expect: 'sceneKey' },
        { in: { teamId: 32, syncWithUrl: true, dashboardItemId: undefined }, expect: 'sceneKey' },
        { in: { teamId: 33, dashboardItemId: Insight123 }, expect: '123' },
        { in: { teamId: 34, dashboardItemId: undefined }, expect: 'defaultKey' },
    ]

    testCases.forEach((testCase) => {
        it(`for ${JSON.stringify(testCase.in)} returns ${JSON.stringify(testCase.expect)}`, () => {
            expect(func(testCase.in)).toEqual(testCase.expect)
        })
    })
})
