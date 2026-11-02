import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

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
        const land = (path: string): void => {
            logic.unmount()
            router.actions.push(path)
            logic = sessionReplaySceneLogic()
            logic.mount()
        }

        it.each([
            [true, true],
            [false, false],
        ])('shows picks when the organization approved AI data processing: %p', (approved, expected) => {
            logic.unmount()
            playlistLogic.unmount()
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: approved,
            })
            playlistLogic = sessionRecordingsPlaylistLogic(SCENE_PLAYLIST_LOGIC_PROPS)
            playlistLogic.mount()
            land('/replay/home')
            expect(logic.values.picksInList).toBe(expected)
        })

        it.each([
            ['Collections', '/replay/playlists', 'playlists'],
            ['Recordings', '/replay/home', 'home'],
            ['an unknown route', '/replay/what-to-watch', 'home'],
        ])('switches to %s', (_, path, tab) => {
            land('/replay/home')
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
