import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { forms } from 'kea-forms'
import type { playerNewPlaylistLogicType } from './playerNewPlaylistLogicType'
import { playerAddToPlaylistLogic } from 'scenes/session-recordings/player/add-to-playlist/playerAddToPlaylistLogic'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import { SessionRecordingPlayerLogicProps } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'

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
    path((key) => ['scenes', 'session-recordings', 'player', 'new-playlist', 'playerNewPlaylistLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey || 'global'}-${props.sessionRecordingId}`),
    connect(() => ({
        actions: [savedSessionRecordingPlaylistModelLogic, ['createSavedPlaylist']],
    })),
    actions({
        createAndGoToPlaylist: true,
    }),
    forms(({ actions, props }) => ({
        newPlaylist: {
            defaults: defaultFormValues,
            errors: ({ name }) => ({
                name: !name ? 'Please give your playlist a name.' : null,
            }),
            submit: async ({ name, description, is_static, show }, breakpoint) => {
                await actions.createSavedPlaylist(
                    {
                        name,
                        description,
                        is_static,
                    },
                    show
                )

                actions.resetNewPlaylist()
                playerAddToPlaylistLogic.findMounted(props)?.actions?.loadPlaylists({})
                savedSessionRecordingPlaylistsLogic
                    .findMounted({ tab: SessionRecordingsTabs.Playlists })
                    ?.actions?.loadPlaylists()
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
