import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from '../../panelLayoutLogic'
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

    it('reveals a folder in the files tab even when the navigation and folder are collapsed', () => {
        const files = projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' })
        panelLayoutLogic.actions.setNavExperimentTab('home')
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(true)
        panelLayoutLogic.actions.setActivePanelIdentifier('DataAndPeople')
        panelLayoutLogic.actions.showLayoutPanel(true)
        files.actions.setSearchTerm('unrelated')
        files.actions.setSortMethod('recent')
        files.actions.setOnlyFolders(true)

        navFilesTabLogic.actions.openFolder('Research/Reports')

        expect(panelLayoutLogic.values.navExperimentActiveTab).toBe('files')
        expect(panelLayoutLogic.values.isNavOverlayOpen).toBe(true)
        expect(panelLayoutLogic.values.activePanelIdentifier).toBe('')
        expect(panelLayoutLogic.values.isLayoutPanelVisible).toBe(false)
        expect(files.values.searchTerm).toBe('')
        expect(files.values.sortMethod).toBe('folder')
        expect(files.values.onlyFolders).toBe(false)
        expect(files.values.expandedFolders).toEqual(
            expect.arrayContaining(['project://Research', 'project://Research/Reports'])
        )
        navFilesTabLogic.actions.openFolder('Research/Reports')
        expect(files.values.expandedFolders).toContain('project://Research/Reports')
    })
})
