import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { sessionRecordingsPlaylistSceneLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistSceneLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('sessionRecordingsPlaylistSceneLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistSceneLogic.build>
    const mockPlaylist = {
        id: 'abc',
        short_id: 'short_abc',
        name: 'Test Playlist',
        type: 'collection' as const,
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
            post: {
                '/api/projects/:team/session_recording_playlists/:id/playlist_viewed': [200, {}],
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
    })

    describe('core assumptions', () => {
        it('loads playlist after mounting', async () => {
            logic.mount()

            await expectLogic(logic).toDispatchActions(['getPlaylistSuccess'])
            expect(logic.values.playlist).toEqual(mockPlaylist)
        })

        it('redirects saved filters to the replay home URL', async () => {
            const savedFilter = { ...mockPlaylist, type: 'filters' as const }
            useMocks({
                get: {
                    '/api/projects/:team/session_recording_playlists/:id': savedFilter,
                },
            })
            router.actions.push(urls.replayPlaylist(savedFilter.short_id))

            logic.mount()

            await expectLogic(logic).toDispatchActions(['getPlaylistSuccess'])
            await expectLogic(logic).toNotHaveDispatchedActions(['updatePlaylist'])
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.replay())
            expect(router.values.searchParams).toEqual({ savedFilterId: savedFilter.short_id })
        })
    })

    describe('update playlist', () => {
        it('set new filter then update playlist', () => {
            logic.mount()

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
