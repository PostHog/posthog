import { shouldShowAddJoinForSidebarItem } from './QueryDatabase'

describe('QueryDatabase', () => {
    describe('shouldShowAddJoinForSidebarItem', () => {
        test.each([
            ['table rows keep add join in the table-specific menu', 'table', false],
            ['views still expose add join', 'view', true],
            ['managed views do not expose add join', 'managed-view', false],
            ['endpoints do not expose add join', 'endpoint', false],
            ['unknown row types do not expose add join', undefined, false],
        ])('%s', (_name, recordType, expected) => {
            expect(shouldShowAddJoinForSidebarItem(recordType)).toEqual(expected)
        })
    })
})
