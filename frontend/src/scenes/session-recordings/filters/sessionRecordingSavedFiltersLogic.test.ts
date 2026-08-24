import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

describe('sessionRecordingSavedFiltersLogic', () => {
    let logic: ReturnType<typeof sessionRecordingSavedFiltersLogic.build>
    const savedFilter = {
        id: 'abc',
        short_id: 'short_abc',
        name: 'Test Saved Filter',
        type: 'filters' as const,
        filters: { events: [], date_from: '2022-10-18' },
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists': { results: [], count: 0 },
                '/api/projects/:team/session_recording_playlists/:id': savedFilter,
            },
        })
        initKeaTests()
        logic = sessionRecordingSavedFiltersLogic()
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
