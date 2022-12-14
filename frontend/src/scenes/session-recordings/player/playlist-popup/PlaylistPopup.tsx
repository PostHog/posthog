import { LemonCheckbox, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconPlus, IconOpenInNew } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { Popup } from 'lib/components/Popup/Popup'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Field } from 'lib/forms/Field'
import { urls } from 'scenes/urls'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { playlistPopupLogic } from './playlistPopupLogic'

export function PlaylistPopup(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { isFullScreen } = useValues(playerSettingsLogic)
    const logic = playlistPopupLogic(props)
    const {
        playlistsLoading,
        searchQuery,
        newFormShowing,
        showPlaylistPopup,
        allPlaylists,
        currentPlaylistsLoading,
        modifiyingPlaylist,
    } = useValues(logic)
    const { setSearchQuery, setNewFormShowing, setShowPlaylistPopup, addToPlaylist, removeFromPlaylist } =
        useActions(logic)

    return (
        <Popup
            visible={showPlaylistPopup}
            onClickOutside={() => setShowPlaylistPopup(false)}
            actionable
            overlay={
                <div className="space-y-1 w-100">
                    <div className="shrink-0 space-y-1">
                        {newFormShowing ? (
                            <Form
                                formKey="newPlaylist"
                                logic={playlistPopupLogic}
                                props={props}
                                enableFormOnSubmit
                                className="space-y-1"
                            >
                                <Field name="name">
                                    <LemonInput placeholder="Playlist name" fullWidth />
                                </Field>
                                <div className="flex items-center gap-2 justify-end">
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={() => setNewFormShowing(false)}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton type="primary" htmlType="submit" icon={<IconPlus />}>
                                        Create and add to list
                                    </LemonButton>
                                </div>
                            </Form>
                        ) : (
                            <>
                                <LemonInput
                                    type="search"
                                    placeholder="Search playlists..."
                                    value={searchQuery}
                                    onChange={setSearchQuery}
                                    fullWidth
                                />
                                <LemonButton fullWidth icon={<IconPlus />} onClick={() => setNewFormShowing(true)}>
                                    New list
                                </LemonButton>
                            </>
                        )}
                    </div>

                    <LemonDivider className="my-1" />

                    {allPlaylists.length ? (
                        <div className="max-h-60 overflow-auto">
                            {allPlaylists?.map(({ selected, playlist }) => (
                                <div key={playlist.short_id} className="flex items-center gap-1">
                                    <LemonButton
                                        className="flex-1"
                                        icon={
                                            currentPlaylistsLoading &&
                                            modifiyingPlaylist?.short_id === playlist.short_id ? (
                                                <Spinner className="text-sm" />
                                            ) : (
                                                <LemonCheckbox className="pointer-events-none" checked={selected} />
                                            )
                                        }
                                        onClick={() =>
                                            !selected ? addToPlaylist(playlist) : removeFromPlaylist(playlist)
                                        }
                                    >
                                        {playlist.name || playlist.derived_name}

                                        {props.playlistShortId === playlist.short_id && (
                                            <span className="text-muted-alt italic text-sm ml-1">(current)</span>
                                        )}
                                    </LemonButton>

                                    <LemonButton
                                        icon={<IconOpenInNew />}
                                        to={urls.sessionRecordingPlaylist(playlist.short_id)}
                                        targetBlank
                                    />
                                </div>
                            ))}
                        </div>
                    ) : playlistsLoading ? (
                        <LemonSkeleton className="my-2" repeat={3} />
                    ) : (
                        <div className="p-2 text-center text-muted">No playlists found</div>
                    )}
                </div>
            }
        >
            <LemonButton
                data-attr="export-button"
                icon={<IconPlus />}
                active={showPlaylistPopup}
                onClick={() => setShowPlaylistPopup(!showPlaylistPopup)}
                size={isFullScreen ? 'small' : 'medium'}
            >
                Pin to list
            </LemonButton>
        </Popup>
    )
}
