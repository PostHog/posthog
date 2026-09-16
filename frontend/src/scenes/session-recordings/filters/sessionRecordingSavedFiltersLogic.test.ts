import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { playlistFiltersLogic } from 'scenes/session-recordings/playlist/playlistFiltersLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

describe('sessionRecordingSavedFiltersLogic', () => {
    let logic: ReturnType<typeof sessionRecordingSavedFiltersLogic.build>
    let savedFiltersRequestCount: number
    const savedFilter = {
        id: 'abc',
        short_id: 'short_abc',
        name: 'Test Saved Filter',
        type: 'filters' as const,
        filters: { events: [], date_from: '2022-10-18' },
    }

    beforeEach(() => {
        savedFiltersRequestCount = 0
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists': () => {
                    savedFiltersRequestCount += 1
                    return { results: [], count: 0 }
                },
                '/api/projects/:team/session_recording_playlists/:id': savedFilter,
            },
        })
        initKeaTests()
        logic = sessionRecordingSavedFiltersLogic()
    })

    it('does not load saved filters when the logic mounts', async () => {
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(savedFiltersRequestCount).toBe(0)
    })

    it('loads saved filters once when the filters panel opens', async () => {
        logic.mount()

        playlistFiltersLogic.actions.setIsFiltersExpanded(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(savedFiltersRequestCount).toBe(1)

        playlistFiltersLogic.actions.setIsFiltersExpanded(false)
        playlistFiltersLogic.actions.setIsFiltersExpanded(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(savedFiltersRequestCount).toBe(1)
    })

    it('redirects to the replay home URL when the saved filter loads on the replay scene', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })

        logic.mount()

        await expectLogic(logic).toDispatchActions(['setAppliedSavedFilter'])
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.replay())
    })

    it('does not redirect a saved filter load that resolves after the user navigated away', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })

        logic.mount()
        router.actions.push(urls.replayVision())

        await expectLogic(logic).toFinishAllListeners().toNotHaveDispatchedActions(['setAppliedSavedFilter'])
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.replayVision())
    })
})
