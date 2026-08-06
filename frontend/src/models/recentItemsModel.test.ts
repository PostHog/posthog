import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api, { ApiConfig } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { recentItemsModel } from './recentItemsModel'

const recentItem = {
    id: 'recent-item',
    path: 'Dashboard',
    type: 'dashboard',
    ref: '1',
    last_viewed_at: '2026-04-22T00:00:00Z',
} as FileSystemEntry

describe('recentItemsModel', () => {
    let logic: ReturnType<typeof recentItemsModel.build>

    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('does not load recent items on mount before the current team ID is known', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(false)
        const listRecents = jest.spyOn(api.fileSystem, 'list').mockResolvedValue({
            count: 0,
            results: [],
            users: [],
        })
        const listSceneLogViews = jest.spyOn(api.fileSystemLogView, 'list').mockResolvedValue([])

        logic = recentItemsModel()
        logic.mount()

        await Promise.resolve()

        expect(listRecents).not.toHaveBeenCalled()
        expect(listSceneLogViews).not.toHaveBeenCalled()
        expect(logic.values.recents).toEqual([])
        expect(logic.values.sceneLogViewsByRef).toEqual({})
    })

    it('loads recent items when the current team becomes available after mount', async () => {
        let hasCurrentTeamId = false
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockImplementation(() => hasCurrentTeamId)
        const listRecents = jest.spyOn(api.fileSystem, 'list').mockResolvedValue({
            count: 1,
            results: [recentItem],
            users: [],
        })
        const listSceneLogViews = jest.spyOn(api.fileSystemLogView, 'list').mockResolvedValue([
            { ref: 'DataManagementScene', type: 'scene', viewed_at: '2026-04-21T00:00:00Z' },
            { ref: 'DataManagementScene', type: 'scene', viewed_at: '2026-04-22T00:00:00Z' },
        ])

        logic = recentItemsModel()
        logic.mount()

        await Promise.resolve()
        expect(listRecents).not.toHaveBeenCalled()
        expect(listSceneLogViews).not.toHaveBeenCalled()

        hasCurrentTeamId = true

        await expectLogic(logic, () => {
            teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        })
            .toDispatchActions(['loadRecentsSuccess', 'loadSceneLogViewsSuccess'])
            .toMatchValues({
                recents: [recentItem],
                sceneLogViewsByRef: {
                    DataManagementScene: '2026-04-22T00:00:00Z',
                },
            })
    })

    it('clears the previous project items on team switch so stale recents are not clickable', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(true)
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({
            count: 1,
            results: [recentItem],
            users: [],
        })
        jest.spyOn(api.fileSystemLogView, 'list').mockResolvedValue([
            { ref: 'DataManagementScene', type: 'scene', viewed_at: '2026-04-22T00:00:00Z' },
        ])

        logic = recentItemsModel()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadRecentsSuccess', 'loadSceneLogViewsSuccess'])
            .toMatchValues({
                recents: [recentItem],
                recentsHasLoaded: true,
                sceneLogViewsHasLoaded: true,
            })

        // Switching projects must wipe the old list synchronously, before the fresh load resolves,
        // so its relative hrefs can't be clicked into the new project and 404.
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        expect(logic.values.recents).toEqual([])
        expect(logic.values.sceneLogViewsByRef).toEqual({})
        expect(logic.values.recentsHasLoaded).toBe(false)
        expect(logic.values.sceneLogViewsHasLoaded).toBe(false)
    })

    it('degrades to empty fallbacks when the loaders hit a fetch failure', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(true)
        jest.spyOn(api.fileSystem, 'list').mockRejectedValue(new TypeError('Failed to fetch'))
        jest.spyOn(api.fileSystemLogView, 'list').mockRejectedValue(new TypeError('Failed to fetch'))

        logic = recentItemsModel()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadRecentsSuccess', 'loadSceneLogViewsSuccess']).toMatchValues({
            recents: [],
            sceneLogViewsByRef: {},
            recentsHasLoaded: true,
            sceneLogViewsHasLoaded: true,
        })
    })
})
