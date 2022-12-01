import { LemonCheckbox, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconPlus, IconOpenInNew } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { Popup } from 'lib/components/Popup/Popup'
import { Field } from 'lib/forms/Field'
import { useEffect, useState } from 'react'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { playlistPopupLogic } from './playlistPopupLogic'

export function PlaylistPopup(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const [showPlaylistPopup, setShowPlaylistPopup] = useState(false)
    const { isFullScreen } = useValues(playerSettingsLogic)
    const logic = playlistPopupLogic(props)
    const { playlists, playlistsLoading, searchQuery, newFormShowing } = useValues(logic)
    const { setSearchQuery, loadPlaylists, setNewFormShowing } = useActions(logic)
    const { setPause } = useActions(sessionRecordingPlayerLogic(props))

    useEffect(() => {
        if (showPlaylistPopup) {
            setPause()
            loadPlaylists()
        }
    }, [showPlaylistPopup])

    return (
        <Popup
            visible={showPlaylistPopup}
            onClickOutside={() => setShowPlaylistPopup(false)}
            actionable
            overlay={
                <div className="space-y-1 w-100">
                    {newFormShowing ? (
                        <>
                            <Form
                                formKey="newPlaylist"
                                logic={playlistPopupLogic}
                                props={props}
                                enableFormOnSubmit
                                className="space-y-2"
                            >
                                <Field name="name" label="Playlist name">
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
                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        icon={<IconPlus />}
                                        onClick={() => setNewFormShowing(true)}
                                    >
                                        Create and add to list
                                    </LemonButton>
                                </div>
                            </Form>
                        </>
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

                    <LemonDivider />

                    {playlists.length ? (
                        <>
                            {playlists?.map((x) => (
                                <div key={x.short_id} className="flex items-center gap-1">
                                    <LemonButton icon={<LemonCheckbox />}>Other playlist</LemonButton>

                                    <LemonButton icon={<IconOpenInNew />} />
                                </div>
                            ))}
                        </>
                    ) : playlistsLoading ? (
                        <LemonSkeleton className="my-2" />
                    ) : (
                        <div className="p-2 text-center text-muted">No playlists found</div>
                    )}
                </div>
            }
        >
            <LemonButton
                data-attr="export-button"
                sideIcon={<IconPlus />}
                active={showPlaylistPopup}
                onClick={() => setShowPlaylistPopup(!showPlaylistPopup)}
                size={isFullScreen ? 'small' : 'medium'}
            >
                Add to list
            </LemonButton>
        </Popup>
    )
}
