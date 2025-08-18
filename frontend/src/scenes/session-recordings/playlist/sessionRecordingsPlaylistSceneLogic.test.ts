import { expectLogic } from 'kea-test-utils'

import { sessionRecordingsPlaylistSceneLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistSceneLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('sessionRecordingsPlaylistSceneLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistSceneLogic.build>
    const mockPlaylist = {
        id: 'abc',
        short_id: 'short_abc',
        name: 'Test Playlist',
        filters: {
            events: [],
            date_from: '2022-10-18',
            session_recording_duration: {
                key: 'duration',
                type: 'recording',
                value: 60,
                operator: 'gt',
            },
        },
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists/:id': mockPlaylist,
            },
            patch: {
                '/api/projects/:team/session_recording_playlists/:id': () => {
                    return [
                        200,
                        {
                            updated_playlist: 'blah',
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    beforeEach(() => {
        logic = sessionRecordingsPlaylistSceneLogic({ shortId: mockPlaylist.short_id })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('loads playlist after mounting', async () => {
            await expectLogic(logic).toDispatchActions(['getPlaylistSuccess'])
            expect(logic.values.playlist).toEqual(mockPlaylist)
        })
    })

    describe('update playlist', () => {
        it('set new filter then update playlist', () => {
            const newFilter = {
                events: [
                    {
                        id: '$autocapture',
                        type: 'events',
                        order: 0,
                        name: '$autocapture',
                    },
                ],
            }
            expectLogic(logic, () => {
                logic.actions.setFilters(newFilter)
                logic.actions.updatePlaylist({})
            })
                .toDispatchActions(['setFilters'])
                .toMatchValues({ filters: expect.objectContaining(newFilter), hasChanges: true })
                .toDispatchActions(['saveChanges', 'updatePlaylist', 'updatePlaylistSuccess'])
                .toMatchValues({
                    playlist: {
                        updated_playlist: 'blah',
                    },
                })
        })
    })
})
