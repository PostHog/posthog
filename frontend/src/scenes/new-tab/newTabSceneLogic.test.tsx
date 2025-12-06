import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { getNewTabProjectTreeLogicProps, matchesFolderSearch, newTabSceneLogic } from './newTabSceneLogic'

describe('newTabSceneLogic - recents search', () => {
    const defaultResponse = {
        results: [],
        count: 0,
        next: null,
        previous: null,
        users: [],
    }

    let logic: ReturnType<typeof newTabSceneLogic.build>
    let listMock: jest.SpiedFunction<typeof api.fileSystem.list>
    let projectTreeDataLogicInstance: ReturnType<typeof projectTreeDataLogic.build>
    let projectTreeLogicInstance: ReturnType<typeof projectTreeLogic.build>

    beforeEach(async () => {
        initKeaTests()
        sceneLogic.mount()

        projectTreeDataLogicInstance = projectTreeDataLogic()
        projectTreeDataLogicInstance.mount()

        projectTreeLogicInstance = projectTreeLogic(getNewTabProjectTreeLogicProps('test-tab'))
        projectTreeLogicInstance.mount()

        listMock = jest.spyOn(api.fileSystem, 'list').mockImplementation(async () => ({ ...defaultResponse }))

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.NEW_TAB_PROJECT_EXPLORER]: true })

        logic = newTabSceneLogic({ tabId: 'test-tab' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        listMock.mockClear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('stores the first recents search prefix with no results', async () => {
        logic.actions.setSearch('no-results')

        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            firstNoResultsSearchPrefixes: expect.objectContaining({ recents: 'no-results' }),
        })

        expect(listMock).toHaveBeenCalledTimes(1)
    })

    it('skips recents searches when extending a known empty prefix', async () => {
        logic.actions.setSearch('none')
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).toHaveBeenCalledTimes(1)

        listMock.mockClear()

        logic.actions.setSearch('none extra')
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).not.toHaveBeenCalled()
    })

    it('tracks no-results prefixes based on filtered recents results', async () => {
        const fileSystemEntry = {
            path: 'project://folder/MyFile',
            type: 'insight',
            last_viewed_at: null,
        } as any

        listMock.mockImplementation(async ({ search }) => {
            if (search === 'folder') {
                return {
                    ...defaultResponse,
                    results: [fileSystemEntry],
                    count: 1,
                }
            }

            return { ...defaultResponse }
        })

        logic.actions.setSearch('folder')
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            firstNoResultsSearchPrefixes: expect.objectContaining({ recents: 'folder' }),
        })

        expect(listMock).toHaveBeenCalledTimes(1)

        listMock.mockClear()

        logic.actions.setSearch('folder deeper')
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).not.toHaveBeenCalled()
    })

    it('loads additional recents with pagination', async () => {
        const PAGINATION_LIMIT = 10
        const INITIAL_LIMIT = 5

        listMock.mockImplementation(async ({ offset = 0, limit = PAGINATION_LIMIT + 1 }) => {
            const results = Array.from({ length: limit }, (_, index) => ({
                path: `project://item-${offset + index}`,
                type: 'insight',
                last_viewed_at: null,
            })) as any

            return {
                ...defaultResponse,
                results,
            }
        })

        logic.actions.setSearch('')
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).toHaveBeenCalledWith(
            expect.objectContaining({
                offset: 0,
                limit: INITIAL_LIMIT + 1,
            })
        )
        expect(logic.values.recents.results).toHaveLength(INITIAL_LIMIT)
        expect(logic.values.recents.hasMore).toBe(true)

        listMock.mockClear()

        logic.actions.loadMoreRecents()
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).toHaveBeenCalledWith(expect.objectContaining({ offset: INITIAL_LIMIT }))
        expect(logic.values.recents.results).toHaveLength(INITIAL_LIMIT + PAGINATION_LIMIT)
        expect(logic.values.sectionItemLimits.recents).toBe(PAGINATION_LIMIT + INITIAL_LIMIT)
    })

    it('expands the limit when a single category is selected', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setNewTabSceneDataInclude(['apps'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.getSectionItemLimit('apps')).toBe(25)
    })

    it('increments recents from the expanded base limit', async () => {
        const PAGINATION_LIMIT = 10

        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setNewTabSceneDataInclude(['recents'])
        await expectLogic(logic).toFinishAllListeners()

        const initialLimit = logic.values.getSectionItemLimit('recents')
        expect(initialLimit).toBe(25)

        logic.actions.loadMoreRecents()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sectionItemLimits.recents).toBe(initialLimit + PAGINATION_LIMIT)
    })

    it('hides explorer-specific features when the flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.NEW_TAB_PROJECT_EXPLORER]: false })

        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            projectExplorerEnabled: false,
            showFoldersCategory: false,
            folderCategoryItems: [],
        })
    })

    it('clears the search input when opening a folder', async () => {
        logic.actions.setSearch('funnel dashboard')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.search).toBe('funnel dashboard')

        logic.actions.setActiveExplorerFolderPath('project://dashboards')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeExplorerFolderPath).toBe('project://dashboards')
        expect(logic.values.search).toBe('')
    })
    it('persists explorer expanded folders per active folder', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setActiveExplorerFolderPath('project://dashboards')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.toggleExplorerFolderExpansion('project://dashboards/reports')

        await expectLogic(logic).toMatchValues({
            explorerExpandedFolders: expect.objectContaining({ 'project://dashboards/reports': true }),
        })

        logic.actions.setActiveExplorerFolderPath('project://dashboards/reports')

        await expectLogic(logic).toMatchValues({ explorerExpandedFolders: {} })

        logic.actions.setActiveExplorerFolderPath('project://dashboards')

        await expectLogic(logic).toMatchValues({
            explorerExpandedFolders: expect.objectContaining({ 'project://dashboards/reports': true }),
        })
    })
    it('exposes folder breadcrumbs for the explorer', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setActiveExplorerFolderPath('top-level/reports')

        await expectLogic(logic).toMatchValues({
            breadcrumbs: [expect.objectContaining({ name: 'reports' })],
        })
    })

    it('searches within the active explorer folder without exiting', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setActiveExplorerFolderPath('project://dashboards')
        await expectLogic(logic).toFinishAllListeners()

        listMock.mockClear()

        logic.actions.setSearch('dash report')
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).toHaveBeenCalledWith(
            expect.objectContaining({ parent: 'project://dashboards', search: 'dash report' })
        )

        await expectLogic(logic).toMatchValues({
            activeExplorerFolderPath: 'project://dashboards',
            explorerSearchResults: expect.objectContaining({
                folderPath: 'project://dashboards',
                searchTerm: 'dash report',
            }),
        })
    })

    it('clears explorer search results when the search term is removed', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setActiveExplorerFolderPath('project://dashboards')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearch('dash report')
        await expectLogic(logic).toFinishAllListeners()

        listMock.mockClear()

        logic.actions.setSearch('')
        await expectLogic(logic).toFinishAllListeners()

        expect(listMock).not.toHaveBeenCalled()

        await expectLogic(logic).toMatchValues({
            explorerSearchResults: expect.objectContaining({ searchTerm: '', folderPath: null, results: [] }),
        })
    })

    it('searches through nested folders when filtering folders', async () => {
        await expectLogic(logic).toFinishAllListeners()

        projectTreeDataLogicInstance.actions.loadFolderSuccess(
            '',
            [
                {
                    id: 'folder-reports',
                    path: 'reports',
                    type: 'folder',
                } as any,
            ],
            false,
            1,
            false
        )

        projectTreeDataLogicInstance.actions.loadFolderSuccess(
            'reports',
            [
                {
                    id: 'folder-monthly',
                    path: 'reports/monthly',
                    type: 'folder',
                } as any,
            ],
            false,
            1,
            false
        )

        logic.actions.setNewTabSceneDataInclude(['folders'])
        logic.actions.setSearch('monthly')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.folderCategoryItems.map((item) => item.record?.path)).toContain('reports/monthly')
    })

    it('hides the folder category when no folders match the search', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setNewTabSceneDataInclude(['folders'])
        logic.actions.setSearch('non-existent-folder')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.folderCategoryItems).toHaveLength(0)
        expect(logic.values.folderHasResults).toBe(false)
    })
})

describe('matchesFolderSearch', () => {
    const folderEntry = {
        path: 'project://dashboards/unfiled/weekly',
        type: 'folder',
    } as FileSystemEntry

    it('matches the final folder segment', () => {
        expect(matchesFolderSearch(folderEntry, 'weekly')).toBe(true)
    })

    it('ignores partial matches in parent folder names', () => {
        expect(matchesFolderSearch(folderEntry, 'unfiled')).toBe(false)
    })

    it('always matches with an empty search term', () => {
        expect(matchesFolderSearch(folderEntry, '')).toBe(true)
    })
})
