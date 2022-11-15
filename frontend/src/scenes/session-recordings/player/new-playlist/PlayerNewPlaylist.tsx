import { LemonDialog } from 'lib/components/LemonDialog'
import { useActions, useValues } from 'kea'
import { playerNewPlaylistLogic } from 'scenes/session-recordings/player/new-playlist/playerNewPlaylistLogic'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { LemonSelect } from 'lib/components/LemonSelect'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'

const PLAYLIST_TYPES = [
    {
        value: true,
        label: 'Static - Updated manually',
        'data-attr': 'playlist-static-option',
    },
    {
        value: false,
        label: 'Dynamic - Updates automatically',
        'data-attr': 'playlist-dynamic-option',
    },
]

function CreateNewPlaylist({}): JSX.Element {
    return (
        <Form logic={playerNewPlaylistLogic} formKey="newPlaylist" id="new-playlist-form" className="space-y-2">
            <Field name="name" label="Name">
                <LemonInput autoFocus={true} data-attr="playlist-name-input" className="ph-ignore-input" />
            </Field>
            <Field name="description" label="Description" showOptional>
                <LemonTextArea data-attr="playlist-description-input" className="ph-ignore-input" />
            </Field>
            <Field name="is_static" label="Static">
                <LemonSelect data-attr="playlist-static-input" className="ph-ignore-input" options={PLAYLIST_TYPES} />
            </Field>
        </Form>
    )
}

function CreatePlaylistButton({
    redirect = false,
    close,
    type = 'secondary',
}: {
    redirect?: boolean
    close: () => void
    type?: LemonButtonProps['type']
}): JSX.Element {
    const { submitNewPlaylist, createAndGoToPlaylist } = useActions(playerNewPlaylistLogic)
    const { newPlaylistHasErrors } = useValues(playerNewPlaylistLogic)
    return (
        <LemonButton
            type={type}
            onClick={() => {
                redirect ? createAndGoToPlaylist() : submitNewPlaylist()
                if (!newPlaylistHasErrors) {
                    close()
                }
            }}
        >
            {redirect ? 'Create and go to playlist' : 'Create'}
        </LemonButton>
    )
}

export function openPlayerNewPlaylistDialog(): void {
    LemonDialog.open({
        title: 'New static playlist',
        description: 'Use static playlists to track multiple recordings from a single view.',
        content: <CreateNewPlaylist />,
        width: '30rem',
        primaryButton: {
            content: function RenderCreatePlaylist(close) {
                return <CreatePlaylistButton close={close} type="primary" />
            },
        },
        secondaryButton: {
            content: function RenderCreatePlaylist(close) {
                return <CreatePlaylistButton close={close} redirect />
            },
        },
        tertiaryButton: {
            children: 'Cancel',
            type: 'secondary',
        },
    })
}
