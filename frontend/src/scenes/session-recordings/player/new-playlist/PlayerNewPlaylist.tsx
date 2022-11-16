import { LemonDialog } from 'lib/components/LemonDialog'
import { useActions, useValues } from 'kea'
import { playerNewPlaylistLogic } from 'scenes/session-recordings/player/new-playlist/playerNewPlaylistLogic'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { LemonSelect } from 'lib/components/LemonSelect'
import { SessionRecordingType } from '~/types'

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

interface PlayerNewPlaylistProps {
    sessionRecordingId?: SessionRecordingType['id']
    defaultStatic?: boolean // if true, only allow static playlist creation
}

function CreateNewPlaylist({ sessionRecordingId, defaultStatic }: PlayerNewPlaylistProps): JSX.Element {
    return (
        <Form
            logic={playerNewPlaylistLogic}
            props={{ sessionRecordingId }}
            formKey="newPlaylist"
            id="new-playlist-form"
            className="space-y-2"
        >
            <Field name="name" label="Name">
                <LemonInput autoFocus={true} data-attr="playlist-name-input" className="ph-ignore-input" />
            </Field>
            <Field name="description" label="Description" showOptional>
                <LemonTextArea data-attr="playlist-description-input" className="ph-ignore-input" />
            </Field>
            {!defaultStatic && (
                <Field name="is_static" label="Type" info="The playlist type cannot be changed after creation.">
                    <LemonSelect
                        data-attr="playlist-static-input"
                        className="ph-ignore-input"
                        options={PLAYLIST_TYPES}
                    />
                </Field>
            )}
        </Form>
    )
}

function CreatePlaylistButton({
    redirect = false,
    close,
    type = 'secondary',
    sessionRecordingId,
}: {
    redirect?: boolean
    close: () => void
    type?: LemonButtonProps['type']
} & PlayerNewPlaylistProps): JSX.Element {
    const logic = playerNewPlaylistLogic({ sessionRecordingId })
    const { submitNewPlaylist, createAndGoToPlaylist } = useActions(logic)
    const { newPlaylistHasErrors } = useValues(logic)
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

export function openPlayerNewPlaylistDialog({
    sessionRecordingId,
    defaultStatic = false,
}: PlayerNewPlaylistProps): void {
    LemonDialog.open({
        title: defaultStatic ? 'New static playlist' : 'New playlist',
        description: `Use ${defaultStatic ? 'static ' : ''}playlists to track multiple recordings from a single view.`,
        content: <CreateNewPlaylist sessionRecordingId={sessionRecordingId} defaultStatic={defaultStatic} />,
        width: '30rem',
        primaryButton: {
            content: function RenderCreatePlaylist(close) {
                return <CreatePlaylistButton sessionRecordingId={sessionRecordingId} close={close} type="primary" />
            },
        },
        secondaryButton: {
            content: function RenderCreatePlaylist(close) {
                return <CreatePlaylistButton sessionRecordingId={sessionRecordingId} close={close} redirect />
            },
        },
        tertiaryButton: {
            children: 'Cancel',
            type: 'secondary',
        },
    })
}
