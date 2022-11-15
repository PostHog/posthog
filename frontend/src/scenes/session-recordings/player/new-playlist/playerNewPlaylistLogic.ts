import { actions, kea, listeners, path } from 'kea'
import { SessionRecordingPlaylistType } from '~/types'
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

export const playerNewPlaylistLogic = kea<playerNewPlaylistLogicType>([
    path(['scenes', 'session-recordings', 'player', 'new-playlist', 'playerNewPlaylistLogic']),
    actions({
        createAndGoToPlaylist: true,
    }),
    forms(({ actions }) => ({
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
                playerAddToPlaylistLogic.findMounted()?.actions?.loadPlaylists({})
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
