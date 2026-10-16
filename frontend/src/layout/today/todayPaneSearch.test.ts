import { viewTypesForPaneSearch } from './todayPaneSearch'

describe('todayPaneSearch', () => {
    test.each([
        ['dash', ['dashboard']],
        ['My Dashboards', ['dashboard']],
        ['notebook', ['notebook']],
        ['canvas', ['canvas']],
        ['da', []],
        ['feature flags', []],
    ])('points a Products search for %s to these view types: %j', (search, types) => {
        expect(viewTypesForPaneSearch(search).map((info) => info.type)).toEqual(types)
    })
})
