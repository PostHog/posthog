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
})
