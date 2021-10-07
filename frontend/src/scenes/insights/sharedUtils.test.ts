import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

describe('keyForInsightLogicProps', () => {
    const func = keyForInsightLogicProps('defaultKey', 'sceneKey')

    it('behaves as expected', () => {
        expect(() => {
            func({})
        }).toThrow('Must init with dashboardItemId, even if undefined')

        expect(func({ syncWithUrl: true, dashboardItemId: undefined })).toEqual('sceneKey')
        expect(func({ syncWithUrl: true, dashboardItemId: 123 })).toEqual('sceneKey')
        expect(func({ dashboardItemId: 123 })).toEqual(123)
        expect(func({ dashboardItemId: undefined })).toEqual('defaultKey')
    })
})
