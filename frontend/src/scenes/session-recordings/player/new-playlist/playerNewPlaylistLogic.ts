import { actions, kea, key, listeners, path, props } from 'kea'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import { forms } from 'kea-forms'
import type { playerNewPlaylistLogicType } from './playerNewPlaylistLogicType'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import { playerAddToPlaylistLogic } from 'scenes/session-recordings/player/add-to-playlist/playerAddToPlaylistLogic'

export interface NewPlaylistForm extends Pick<SessionRecordingPlaylistType, 'name' | 'description' | 'is_static'> {
    show: boolean
}

const defaultFormValues: NewPlaylistForm = {
    name: '',
    description: '',
    is_static: true,
    show: false,
}

export interface PlayerNewPlaylistLogicProps {
    sessionRecordingId?: SessionRecordingType['id']
}

export const playerNewPlaylistLogic = kea<playerNewPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'new-playlist', 'playerNewPlaylistLogic', key]),
    props({} as PlayerNewPlaylistLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'global'),
    actions({
        createAndGoToPlaylist: true,
    }),
    forms(({ actions, key }) => ({
        newPlaylist: {
            defaults: defaultFormValues,
            errors: ({ name }) => ({
                name: !name ? 'Please give your playlist a name.' : null,
            }),
            submit: async ({ name, description, is_static, show }, breakpoint) => {
                await createPlaylist(
                    {
                        name,
                        description,
                        is_static,
                    },
                    show
                )

                actions.resetNewPlaylist()
                playerAddToPlaylistLogic.findMounted({ recording: { id: key } })?.actions?.loadPlaylists({})
                breakpoint()
            },
        },
    })),
    listeners(({ actions }) => ({
        createAndGoToPlaylist: () => {
            actions.setNewPlaylistValue('show', true)
            actions.submitNewPlaylist()
        },
    })),
])
