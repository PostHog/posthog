import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { sessionRecordingsPlaylistLogic } from './playlist/sessionRecordingsPlaylistLogic'
import { SCENE_PLAYLIST_LOGIC_PROPS, sessionReplaySceneLogic } from './sessionReplaySceneLogic'

describe('sessionReplaySceneLogic', () => {
    let logic: ReturnType<typeof sessionReplaySceneLogic.build>
    let playlistLogic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push('/replay/home', { sessionRecordingId: 'session-a', t: 42 })
        logic = sessionReplaySceneLogic()
        logic.mount()
        playlistLogic = sessionRecordingsPlaylistLogic(SCENE_PLAYLIST_LOGIC_PROPS)
        playlistLogic.mount()
    })

    afterEach(() => {
        playlistLogic.unmount()
        logic.unmount()
    })

    describe('landing on the tab arms', () => {
        const land = (variant: string, path: string, params: Record<string, any> = {}): void => {
            logic.unmount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.REPLAY_VISION_WATCH_IN_LIST_EXPERIMENT]: variant,
            })
            router.actions.push(path, params)
            logic = sessionReplaySceneLogic()
            logic.mount()
        }

        it.each([
            ['the tab arm on the bare home route', 'watch-tab', '/replay/home', {}, '/replay/what-to-watch'],
            ['both arms on the bare home route', 'both', '/replay/home', {}, '/replay/what-to-watch'],
            ['the in-list arm', 'in-list', '/replay/home', {}, '/replay/home'],
            ['a deep link to a recording', 'watch-tab', '/replay/home', { sessionRecordingId: 'x' }, '/replay/home'],
            ['a link with filters', 'watch-tab', '/replay/home', { filters: { date_from: '-30d' } }, '/replay/home'],
            ['another tab', 'watch-tab', '/replay/playlists', {}, '/replay/playlists'],
        ])('lands %s where expected', (_, variant, path, params, expected) => {
            land(variant, path, params)
            expect(router.values.location.pathname).toMatch(new RegExp(`${expected}$`))
        })

        it('hides every arm when the organization has not approved AI data processing', () => {
            logic.unmount()
            playlistLogic.unmount()
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: false,
            })
            playlistLogic = sessionRecordingsPlaylistLogic(SCENE_PLAYLIST_LOGIC_PROPS)
            playlistLogic.mount()
            land('both', '/replay/home')
            expect(logic.values.watchPicksVariant).toBeNull()
            expect(router.values.location.pathname).toMatch(/\/replay\/home$/)
        })

        it.each([
            ['Collections', '/replay/playlists', 'playlists'],
            ['What to watch', '/replay/what-to-watch', 'what-to-watch'],
            ['Recordings', '/replay/home', 'home'],
        ])('switches to %s after landing', (_, path, tab) => {
            land('both', '/replay/home')
            router.actions.push(path)
            expect(logic.values.tab).toBe(tab)
            expect(router.values.location.pathname).toMatch(new RegExp(`${path}$`))
        })

        it('redirects once per visit, so the Recordings tab stays reachable', () => {
            land('watch-tab', '/replay/home')
            router.actions.push('/replay/home')
            expect(router.values.location.pathname).toMatch(/\/replay\/home$/)
        })
    })

    it.each([
        ['a deep link with no pick', null, 'session-b', 42],
        ['the same pick again', 'session-a', 'session-a', 42],
        ['another recording after a pick', 'session-a', 'session-b', undefined],
    ])('keeps the seek param for %s', async (_, pickSessionId, nextId, expectedT) => {
        logic.actions.setPickSeekSessionId(pickSessionId)
        await expectLogic(logic, () => {
            playlistLogic.actions.setSelectedRecordingId(nextId)
        }).toFinishAllListeners()
        expect(router.values.searchParams.t).toBe(expectedT)
    })
})
