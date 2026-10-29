import { analyticsTypesForPaneSearch } from './todayPaneSearch'

describe('todayPaneSearch', () => {
    test.each([
        ['dash', ['dashboard']],
        ['My Dashboards', ['dashboard']],
        ['notebook', ['notebook']],
        ['canvas', ['canvas']],
        ['insights', ['insight']],
        ['da', []],
        ['feature flags', []],
    ])('points a Products search for %s to these analytics types: %j', (search, types) => {
        expect(analyticsTypesForPaneSearch(search).map((info) => info.type)).toEqual(types)
    })
})
