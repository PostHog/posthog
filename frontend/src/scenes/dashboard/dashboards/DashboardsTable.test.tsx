import { getDashboardFolderLabelFromItems } from './DashboardsTable'

describe('getDashboardFolderLabelFromItems', () => {
    it('returns first folder segment for Unfiled/Foo', () => {
        const label = getDashboardFolderLabelFromItems(
            {
                'dashboard::1': { path: 'Unfiled/Foo' },
            },
            1
        )
        expect(label).toEqual('Unfiled')
    })

    it('returns all but last segment joined with / for Foo/Bar/Baz', () => {
        const label = getDashboardFolderLabelFromItems(
            {
                'dashboard::2': { path: 'Foo/Bar/Baz' },
            },
            2
        )
        expect(label).toEqual('Foo / Bar')
    })

    it('returns em dash when there is no entry or no folder segments', () => {
        const itemsByRef = {
            'dashboard::3': { path: 'RootOnly' },
        }

        expect(getDashboardFolderLabelFromItems(itemsByRef, 3)).toEqual('—')
        expect(getDashboardFolderLabelFromItems(itemsByRef, 999)).toEqual('—')
    })
})
