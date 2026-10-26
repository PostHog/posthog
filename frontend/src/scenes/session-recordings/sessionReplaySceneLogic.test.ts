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
        localStorage.clear()
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
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

    describe('picks in the recordings list', () => {
        const land = (variant: string, path: string, otherFlags: Record<string, string> = {}): void => {
            logic.unmount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.REPLAY_VISION_WATCH_IN_LIST_EXPERIMENT]: variant,
                ...otherFlags,
            })
            router.actions.push(path)
            logic = sessionReplaySceneLogic()
            logic.mount()
        }

        it.each([
            ['the in-list arm', 'in-list', true],
            ['control', 'control', false],
            ['the watch-tab arm', 'watch-tab', false],
            ['the both arm', 'both', false],
        ])('shows picks for %s: %p', (_, variant, expected) => {
            land(variant, '/replay/home')
            expect(logic.values.picksInList).toBe(expected)
        })

        it('leaves users on the replay redesign out of the experiment', () => {
            land('in-list', '/replay/home', { [FEATURE_FLAGS.REPLAY_UI_REDESIGN_2026]: 'test' })
            expect(logic.values.picksInList).toBe(false)
        })

        it('hides the picks when the organization has not approved AI data processing', () => {
            logic.unmount()
            playlistLogic.unmount()
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: false,
            })
            playlistLogic = sessionRecordingsPlaylistLogic(SCENE_PLAYLIST_LOGIC_PROPS)
            playlistLogic.mount()
            land('in-list', '/replay/home')
            expect(logic.values.picksInList).toBe(false)
        })

        it.each([
            ['Collections', '/replay/playlists', 'playlists'],
            ['Recordings', '/replay/home', 'home'],
            ['an unknown route', '/replay/what-to-watch', 'home'],
        ])('switches to %s', (_, path, tab) => {
            land('in-list', '/replay/home')
            router.actions.push(path)
            expect(logic.values.tab).toBe(tab)
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
