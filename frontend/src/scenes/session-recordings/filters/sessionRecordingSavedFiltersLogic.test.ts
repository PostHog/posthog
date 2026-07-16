import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

import { sessionRecordingSavedFiltersLogic } from './sessionRecordingSavedFiltersLogic'

describe('sessionRecordingSavedFiltersLogic', () => {
    const savedFilter = {
        id: 'saved-filter-id',
        short_id: 'saved-filter-short-id',
        name: 'Saved filter',
        type: 'filters' as const,
        filters: {
            date_from: '-7d',
            filter_group: {
                type: 'AND' as const,
                values: [],
            },
        },
    }
    const getPlaylistMock = jest.fn(() => savedFilter)

    beforeEach(() => {
        getPlaylistMock.mockClear()
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists/': {
                    results: [],
                    count: 0,
                    filters: null,
                },
                '/api/projects/:team/session_recording_playlists/:id': getPlaylistMock,
            },
        })
        initKeaTests()
    })

    it.each([
        ['when the logic mounts', false],
        ['after the logic is already mounted', true],
    ])('applies a saved filter from the URL %s', async (_, mountBeforeNavigation) => {
        const logic = sessionRecordingSavedFiltersLogic()

        if (mountBeforeNavigation) {
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSavedFiltersSuccess'])
        }

        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })

        if (!mountBeforeNavigation) {
            logic.mount()
        }

        await expectLogic(logic).toDispatchActions(['checkForSavedFilterRedirect', 'setAppliedSavedFilter'])

        expect(getPlaylistMock).toHaveBeenCalledTimes(1)
        expect(logic.values.appliedSavedFilter).toEqual(savedFilter)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.replay(ReplayTabs.Home))
        expect(router.values.searchParams.savedFilterId).toBeUndefined()
        expect(router.values.searchParams.filters).toEqual(savedFilter.filters)
    })
})
