import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

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
