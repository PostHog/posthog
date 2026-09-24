import { initKeaTests } from '~/test/init'

import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { FILES_STARRED_TREE_KEY, FILES_TREE_KEY, navFilesTabLogic } from './navFilesTabLogic'

describe('navFilesTabLogic', () => {
    beforeEach(() => {
        initKeaTests()
        navFilesTabLogic.mount()
    })

    it('filters starred files with the file search and restores them when cleared', () => {
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'overview', path: 'Overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
            { id: 'research', path: 'Research', type: 'folder', ref: 'Research' },
        ])
        const files = projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' })
        const starred = projectTreeLogic({ key: FILES_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'files' })

        files.actions.setSearchTerm('Overview')
        expect(starred.values.fullFileSystemFiltered.map((item) => item.name)).toEqual(['Overview'])

        files.actions.setSearchTerm('no match')
        expect(starred.values.fullFileSystemFiltered).toEqual([])

        files.actions.clearSearch()
        expect(starred.values.fullFileSystemFiltered.map((item) => item.name)).toEqual(['Overview', 'Research'])
    })

    it('combines ownership and type filters without dropping text or desynchronizing starred files', () => {
        const files = projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' })
        const starred = projectTreeLogic({ key: FILES_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'files' })

        files.actions.setSearchTerm('Overview')
        files.actions.toggleOnlyMyStuff()
        files.actions.toggleFileTypeFilter('insight')
        expect(files.values.searchTerm).toBe('Overview user:me type:insight')
        expect(files.values.searchFilters).toEqual({ onlyMine: true, fileType: 'insight' })
        expect(starred.values.searchTerm).toBe(files.values.searchTerm)

        files.actions.toggleFileTypeFilter('dashboard')
        expect(files.values.searchTerm).toBe('Overview user:me type:dashboard')

        files.actions.toggleOnlyMyStuff()
        expect(files.values.searchTerm).toBe('Overview type:dashboard')
        files.actions.toggleFileTypeFilter('dashboard')
        expect(files.values.searchTerm).toBe('Overview')
        expect(files.values.searchFilters).toEqual({ onlyMine: false, fileType: null })
        expect(starred.values.searchTerm).toBe('Overview')
    })
})
