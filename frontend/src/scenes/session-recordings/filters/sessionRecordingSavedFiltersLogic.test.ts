import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
    let savedFilterRequestCount: number
    const savedFilter = {
        id: 'abc',
        short_id: 'short_abc',
        name: 'Test Saved Filter',
        type: 'filters' as const,
        filters: { events: [], date_from: '2022-10-18' },
    }

    let deleteSucceeds: boolean

    beforeEach(() => {
        savedFiltersRequestCount = 0
        savedFilterRequestCount = 0
        deleteSucceeds = true
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists': () => {
                    savedFiltersRequestCount += 1
                    return { results: [], count: 0 }
                },
                '/api/projects/:team/session_recording_playlists/:id': () => {
                    savedFilterRequestCount += 1
                    return savedFilter
                },
            },
            patch: {
                '/api/projects/:team/session_recording_playlists/:id': () =>
                    deleteSucceeds ? [200, savedFilter] : [500, { detail: 'nope' }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
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

    it('loads saved filters once when a navigation menu opens', async () => {
        logic.mount()

        logic.actions.loadSavedFiltersIfNeeded()
        await expectLogic(logic).toFinishAllListeners()
        expect(savedFiltersRequestCount).toBe(1)

        logic.actions.loadSavedFiltersIfNeeded()
        await expectLogic(logic).toFinishAllListeners()
        expect(savedFiltersRequestCount).toBe(1)
    })

    it('loads saved filters when the filters panel was expanded before the logic mounted', async () => {
        playlistFiltersLogic.mount()
        playlistFiltersLogic.actions.setIsFiltersExpanded(true)

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(savedFiltersRequestCount).toBe(1)
    })

    it('redirects to the replay home URL when the saved filter loads on the replay scene', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })

        logic.mount()

        await expectLogic(logic).toDispatchActions(['setAppliedSavedFilter'])
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.replay())
    })

    it('applies a saved filter from a URL that already carries filters without redirecting', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home), {
            savedFilterId: savedFilter.short_id,
            filters: { date_from: '-7d' },
        })

        logic.mount()

        await expectLogic(logic).toDispatchActions(['setAppliedSavedFilter'])
        expect(router.values.searchParams).toEqual({
            savedFilterId: savedFilter.short_id,
            filters: { date_from: '-7d' },
        })
    })

    it('fetches a saved filter once while the list rewrites the URL', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })
        logic.mount()
        router.actions.replace(urls.replay(ReplayTabs.Home), {
            savedFilterId: savedFilter.short_id,
            filters: { date_from: '-7d' },
        })

        await expectLogic(logic).toDispatchActions(['setAppliedSavedFilter'])
        expect(savedFilterRequestCount).toBe(1)
    })

    it('applies a saved filter link while already open', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home))
        logic.mount()

        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })

        await expectLogic(logic).toDispatchActions(['setAppliedSavedFilter'])
        expect(logic.values.appliedSavedFilter).toEqual(savedFilter)
    })

    it.each([
        ['the replay home in the new layout', urls.replay(ReplayTabs.Home), 'compact', savedFilter.short_id],
        ['the replay home in the classic layout', urls.replay(ReplayTabs.Home), 'control', undefined],
        ['another page', urls.replayVision(), 'compact', undefined],
    ])('writes the applied saved filter into the URL of %s', (_, path, arm, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.REPLAY_WATCH_LAYOUT]: arm })
        router.actions.push(path)
        logic.mount()

        logic.actions.setAppliedSavedFilter(savedFilter as any)
        expect(router.values.searchParams.savedFilterId).toEqual(expected)

        logic.actions.setAppliedSavedFilter(null)
        expect(router.values.searchParams.savedFilterId).toBeUndefined()
    })

    it.each([
        ['clears the applied filter when its delete succeeds', true, null],
        ['keeps the applied filter when its delete fails', false, savedFilter],
    ])('%s', async (_, succeeds, expected) => {
        deleteSucceeds = succeeds
        logic.mount()
        logic.actions.setAppliedSavedFilter(savedFilter as any)

        logic.actions.deletePlaylist(savedFilter as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.appliedSavedFilter).toEqual(expected)
    })

    it('does not redirect a saved filter load that resolves after the user navigated away', async () => {
        router.actions.push(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })

        logic.mount()
        router.actions.push(urls.replayVision())

        await expectLogic(logic).toFinishAllListeners().toNotHaveDispatchedActions(['setAppliedSavedFilter'])
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.replayVision())
    })
})
