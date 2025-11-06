import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sceneLogic } from 'scenes/sceneLogic'

import { featureFlagLogic } from '~/lib/logic/featureFlagLogic'
import { initKeaTests } from '~/test/init'

import { newTabSceneLogic } from './newTabSceneLogic'

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

    beforeEach(async () => {
        initKeaTests()
        sceneLogic.mount()

        featureFlagLogic.actions.setFeatureFlags([], { 'new-tab-folders': true } as any)

        listMock = jest.spyOn(api.fileSystem, 'list').mockImplementation(async () => ({ ...defaultResponse }))

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

    it('searches project folders by folder name only', async () => {
        logic.actions.setSearch('Feature flags')
        await expectLogic(logic).toFinishAllListeners()

        const folderCall = listMock.mock.calls.find(([params]) => params?.type === 'folder')

        expect(folderCall?.[0]).toMatchObject({ search: 'name:Feature name:flags' })
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

        expect(logic.values.getSectionItemLimit('apps')).toBe(15)
    })

    it('increments recents from the expanded base limit', async () => {
        const PAGINATION_LIMIT = 10

        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setNewTabSceneDataInclude(['recents'])
        await expectLogic(logic).toFinishAllListeners()

        const initialLimit = logic.values.getSectionItemLimit('recents')
        expect(initialLimit).toBe(15)

        logic.actions.loadMoreRecents()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sectionItemLimits.recents).toBe(initialLimit + PAGINATION_LIMIT)
    })
})
