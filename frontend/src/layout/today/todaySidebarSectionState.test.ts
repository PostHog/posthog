import {
    TodaySidebarSectionInput,
    TodaySidebarSectionState,
    todayRecentClearLabel,
    todaySidebarSectionState,
} from './todaySidebarSectionState'

describe('todaySidebarSectionState', () => {
    test.each<[string, TodaySidebarSectionInput, TodaySidebarSectionState]>([
        ['a first load is not read as empty', { loading: true, failed: false, total: 0, shown: 0 }, 'loading'],
        ['a failed load is not read as empty', { loading: false, failed: true, total: 0, shown: 0 }, 'error'],
        ['a settled load with no rows is empty', { loading: false, failed: false, total: 0, shown: 0 }, 'empty'],
        [
            'rows that search or filters hide are no matches',
            { loading: false, failed: false, total: 3, shown: 0 },
            'no-matches',
        ],
        ['a reload keeps the rows it has', { loading: true, failed: false, total: 3, shown: 3 }, 'ready'],
        ['a failed refresh keeps the rows it has', { loading: false, failed: true, total: 3, shown: 2 }, 'ready'],
    ])('%s', (_, input, expected) => {
        expect(todaySidebarSectionState(input)).toEqual(expected)
    })

    test.each<[boolean, boolean, string]>([
        [true, false, 'Clear search'],
        [false, true, 'Clear filters'],
        [true, true, 'Clear search and filters'],
    ])('names what clearing removes when search is %s and filters are %s', (searching, filtering, expected) => {
        expect(todayRecentClearLabel(searching, filtering)).toEqual(expected)
    })
})
