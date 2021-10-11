import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

describe('keyForInsightLogicProps', () => {
    const func = keyForInsightLogicProps('defaultKey', 'sceneKey')

    it('throws if no dashboardItemId', () => {
        expect(() => {
            func({})
        }).toThrow('Must init with dashboardItemId, even if undefined')
    })

    const testCases = [
        { in: { syncWithUrl: true, dashboardItemId: 123 }, expect: 'sceneKey' },
        { in: { syncWithUrl: true, dashboardItemId: undefined }, expect: 'sceneKey' },
        { in: { dashboardItemId: 123 }, expect: 123 },
        { in: { dashboardItemId: undefined }, expect: 'defaultKey' },
    ]

    testCases.forEach((testCase) => {
        it(`for ${JSON.stringify(testCase.in)} returns ${JSON.stringify(testCase.expect)}`, () => {
            expect(func(testCase.in)).toEqual(testCase.expect)
        })
    })
})
