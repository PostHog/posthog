import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

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

    afterEach(() => jest.restoreAllMocks())

    it.each([false, true])('loads nested folder contents with cached expansion: %s', async (expanded) => {
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        const files = projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://', isActiveInPanel: true })
        const folder = { id: 'reports', path: 'Unfiled/Reports', type: 'folder', ref: 'Unfiled/Reports' }
        const note = { id: 'note', path: 'Unfiled/Reports/Notes', type: 'notebook', ref: 'note' }
        let resolveRoot!: (response: { count: number; results: (typeof folder)[]; users: [] }) => void
        jest.spyOn(api.fileSystem, 'list').mockImplementation(({ parent } = {}) => {
            if (parent === '') {
                return new Promise((resolve) => {
                    resolveRoot = resolve
                })
            }
            const results = parent === 'Unfiled' ? [folder] : parent === folder.path ? [note] : []
            return Promise.resolve({ count: results.length, results, users: [] })
        })
        files.actions.setExpandedFolders(
            expanded ? ['project://', 'project://Unfiled', 'project://Unfiled/Reports'] : ['project://']
        )
        projectTreeDataLogic.actions.loadFolder('', true)

        navFilesTabLogic.actions.openFolder(folder.path)
        await expectLogic(projectTreeDataLogic, () => {
            resolveRoot({
                count: 1,
                results: [{ ...folder, id: 'unfiled', path: 'Unfiled', ref: 'Unfiled' }],
                users: [],
            })
        }).toFinishAllListeners()

        expect(files.values.expandedFolders).toEqual(
            expect.arrayContaining(['project://Unfiled', 'project://Unfiled/Reports'])
        )
        expect(files.values.folders.Unfiled).toEqual([folder])
        expect(files.values.folders[folder.path]).toEqual([note])
    })

    it('preserves folder pagination when reopening a nested folder', async () => {
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        const files = projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' })
        const folder = { id: 'reports', path: 'Research/Reports', type: 'folder', ref: 'Research/Reports' }
        const note = { id: 'note', path: 'Research/Reports/Notes', type: 'notebook', ref: 'note' }
        files.actions.setExpandedFolders(['project://', 'project://Research', 'project://Research/Reports'])
        projectTreeDataLogic.actions.loadFolderSuccess('Research', [folder], true, 100)
        projectTreeDataLogic.actions.loadFolderSuccess(folder.path, [note], true, 100)
        const list = jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })

        await expectLogic(files, () => navFilesTabLogic.actions.openFolder(folder.path)).toFinishAllListeners()

        expect(list).not.toHaveBeenCalled()
        expect(files.values.folderStates.Research).toBe('has-more')
        expect(files.values.folderStates[folder.path]).toBe('has-more')
        expect(files.values.folders[folder.path]).toEqual([note])

        await expectLogic(projectTreeDataLogic, () => files.actions.loadFolder(folder.path)).toFinishAllListeners()
        expect(list).toHaveBeenCalledWith(expect.objectContaining({ parent: folder.path, offset: 100 }))
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

    it('reveals a folder in the files tab even when the navigation and folder are collapsed', async () => {
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
        expect(files.values.scrollTargetId).toBe('')
        await expectLogic(files, () => {
            projectTreeDataLogic.actions.loadFolderSuccess(
                'Research',
                [{ id: 'reports', path: 'Research/Reports', type: 'folder', ref: 'Research/Reports' }],
                false,
                1
            )
        }).toMatchValues({ scrollTargetId: 'project://Research/Reports' })
        files.actions.clearScrollTarget()
        projectTreeDataLogic.actions.loadFolderSuccess('Research/Reports', [], false, 0)
        expect(files.values.scrollTargetId).toBe('')
        navFilesTabLogic.actions.openFolder('Research/Reports')
        expect(files.values.expandedFolders).toContain('project://Research/Reports')
        expect(files.values.scrollTargetId).toBe('project://Research/Reports')
    })
})
