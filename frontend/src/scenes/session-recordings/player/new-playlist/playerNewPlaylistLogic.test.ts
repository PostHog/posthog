import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import { expectLogic } from 'kea-test-utils'
import { playerNewPlaylistLogic } from 'scenes/session-recordings/player/new-playlist/playerNewPlaylistLogic'

describe('playerNewPlaylistLogic', () => {
    let logic: ReturnType<typeof playerNewPlaylistLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists/:id': [200, 'retrieved playlist'],
            },
            post: {
                '/api/projects/:team/session_recording_playlists': [200, 'created playlists'],
            },
            patch: {
                '/api/projects/:team/session_recording_playlists/:id': [200, 'updated playlist'],
                '/api/projects/:team/session_recordings/:id': [
                    200,
                    {
                        result: {
                            session_recording: 'updated recording',
                        },
                    },
                ],
            },
        })
        initKeaTests()
    })

    describe('core assumptions', () => {
        beforeEach(() => {
            logic = playerNewPlaylistLogic()
            logic.mount()
        })

        it('mounts a bunch of other logics', async () => {
            await expectLogic(logic).toMount([savedSessionRecordingPlaylistModelLogic])
        })
    })

    describe('creating playlists', () => {
        beforeEach(() => {
            logic = playerNewPlaylistLogic()
            logic.mount()
        })
        it('createPlaylist', async () => {
            await expectLogic(logic, async () => {
                await logic.actions.setNewPlaylistValues({
                    name: 'blah',
                    description: 'blah description',
                    is_static: true,
                })
                logic.actions.submitNewPlaylist()
            }).toDispatchActions(['setNewPlaylistValues', 'submitNewPlaylist', 'submitNewPlaylistSuccess'])
        })
        it('createPlaylist with no name', async () => {
            await expectLogic(logic, async () => {
                await logic.actions.setNewPlaylistValues({
                    description: 'blah description',
                    is_static: true,
                })
                logic.actions.submitNewPlaylist()
            })
                .toDispatchActions(['setNewPlaylistValues', 'submitNewPlaylist', 'submitNewPlaylistFailure'])
                .toMatchValues({
                    newPlaylistErrors: {
                        name: 'Please give your playlist a name.',
                    },
                })
        })
        it('createAndGoToPlaylist', async () => {
            await expectLogic(logic, async () => {
                await logic.actions.setNewPlaylistValues({
                    name: 'blah',
                    description: 'blah description',
                })
                logic.actions.createAndGoToPlaylist()
            })
                .toDispatchActions(['setNewPlaylistValue'])
                .toMatchValues({
                    newPlaylist: expect.objectContaining({
                        show: true,
                    }),
                })
                .toDispatchActions(['submitNewPlaylist', 'submitNewPlaylistSuccess'])
        })
    })
})
