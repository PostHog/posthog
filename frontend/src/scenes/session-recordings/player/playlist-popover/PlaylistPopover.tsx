import { LemonCheckbox, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconPlus, IconOpenInNew, IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Field } from 'lib/forms/Field'
import { urls } from 'scenes/urls'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { playlistPopoverLogic } from './playlistPopoverLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'

export function PlaylistPopover(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const dataLogic = sessionRecordingDataLogic(props)
    const { sessionPlayerData } = useValues(dataLogic)
    const logic = playlistPopoverLogic(props)
    const {
        playlistsLoading,
        searchQuery,
        newFormShowing,
        showPlaylistPopover,
        allPlaylists,
        currentPlaylistsLoading,
        modifyingPlaylist,
    } = useValues(logic)
    const { setSearchQuery, setNewFormShowing, setShowPlaylistPopover, addToPlaylist, removeFromPlaylist } =
        useActions(logic)

    return (
        <IconWithCount count={sessionPlayerData.metadata.pinnedCount ?? 0} showZero={false}>
            <Popover
                visible={showPlaylistPopover}
                onClickOutside={() => setShowPlaylistPopover(false)}
                actionable
                overlay={
                    <div className="space-y-1 w-100">
                        <div className="shrink-0 space-y-1">
                            {newFormShowing ? (
                                <Form
                                    formKey="newPlaylist"
                                    logic={playlistPopoverLogic}
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
                                                modifyingPlaylist?.short_id === playlist.short_id ? (
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
                    active={showPlaylistPopover}
                    onClick={() => setShowPlaylistPopover(!showPlaylistPopover)}
                    size={'small'}
                >
                    <span>Pin to list</span>
                </LemonButton>
            </Popover>
        </IconWithCount>
    )
}
