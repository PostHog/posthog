import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import { expectLogic } from 'kea-test-utils'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'

describe('savedSessionRecordingPlaylistModelLogic', () => {
    let logic: ReturnType<typeof savedSessionRecordingPlaylistModelLogic.build>

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

    describe('playlist logic', () => {
        beforeEach(() => {
            logic = savedSessionRecordingPlaylistModelLogic()
            logic.mount()
        })
        it('loadSavedPlaylist', async () => {
            expectLogic(logic, () => {
                logic.actions.loadSavedPlaylist('abc')
            })
                .toDispatchActions(['loadSavedPlaylist', 'loadSavedPlaylistSuccess'])
                .toMatchValues({
                    _playlistModel: 'retrieved playlist',
                })
        })
        it('createSavedPlaylist', () => {
            expectLogic(logic, () => {
                logic.actions.createSavedPlaylist({ name: 'test' })
            })
                .toDispatchActions(['createSavedPlaylist', 'createSavedPlaylistSuccess'])
                .toMatchValues({
                    _playlistModel: 'created playlist',
                })
        })
        it('duplicateSavedPlaylist', () => {
            expectLogic(logic, () => {
                logic.actions.duplicateSavedPlaylist({ name: 'test' })
            })
                .toDispatchActions(['duplicateSavedPlaylist', 'duplicateSavedPlaylistSuccess'])
                .toMatchValues({
                    _playlistModel: 'created playlist',
                })
        })
        it('updateSavedPlaylist', () => {
            expectLogic(logic, () => {
                logic.actions.updateSavedPlaylist({ id: 1, short_id: 'abc', name: 'test' })
            })
                .toDispatchActions(['updateSavedPlaylist', 'updateSavedPlaylistSuccess'])
                .toMatchValues({
                    _playlistModel: 'updated playlist',
                })
        })
        it('deleteSavedPlaylistWithUndo', () => {
            expectLogic(logic, () => {
                logic.actions.deleteSavedPlaylistWithUndo({ id: 1, short_id: 'abc', name: 'test' })
            })
                .toDispatchActions(['deleteSavedPlaylistWithUndo', 'deleteSavedPlaylistWithUndoSuccess'])
                .toMatchValues({
                    _playlistModel: 'updated playlist',
                })
        })
    })

    describe('recording logic', () => {
        const recording = { id: 'nightly', viewed: false, recording_duration: 10, playlists: [1, 2] }

        beforeEach(() => {
            jest.spyOn(api, 'update')
            logic = savedSessionRecordingPlaylistModelLogic()
            logic.mount()
        })
        it('addRecordingToPlaylist', async () => {
            expectLogic(logic, () => {
                logic.actions.addRecordingToPlaylist(recording, {
                    id: 3,
                    short_id: 'abc',
                    name: 'blank',
                    playlist_items: [],
                    is_static: true,
                })
            })
                .toDispatchActions(['addRecordingToPlaylist', 'addRecordingToPlaylistSuccess'])
                .toMatchValues({
                    _recordingModel: 'updated recording',
                })

            expect(api.update).toBeCalledWith(`api/projects/${MOCK_TEAM_ID}/session_recordings/nightly`, {
                playlists: [1, 2, 3],
            })
        })
        it('removeRecordingFromPlaylist', () => {
            expectLogic(logic, () => {
                logic.actions.removeRecordingFromPlaylist(recording, {
                    id: 1,
                    short_id: 'abc',
                    name: 'blank',
                    playlist_items: [],
                    is_static: true,
                })
            })
                .toDispatchActions(['removeRecordingFromPlaylist', 'removeRecordingFromPlaylistSuccess'])
                .toMatchValues({
                    _recordingModel: 'updated recording',
                })

            expect(api.update).toBeCalledWith(`api/projects/${MOCK_TEAM_ID}/session_recordings/nightly`, {
                playlists: [2],
            })
        })
    })
})
