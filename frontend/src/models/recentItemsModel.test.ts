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
})
