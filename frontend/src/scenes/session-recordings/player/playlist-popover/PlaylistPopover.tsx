import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPin, IconPlus } from '@posthog/icons'
import { LemonCheckbox, LemonDivider } from '@posthog/lemon-ui'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew, IconWithCount } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { sessionRecordingsPlaylistLogic } from '../../playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playlistPopoverLogic } from './playlistPopoverLogic'

export function PlaylistPopoverButton({
    setPinnedInCurrentPlaylist,
    ...buttonProps
}: { setPinnedInCurrentPlaylist?: (pinned: boolean) => void } & LemonButtonProps): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const {
        logicProps: { logicKey: currentPlaylistId },
    } = useValues(sessionRecordingsPlaylistLogic)

    const logic = playlistPopoverLogic(logicProps)
    const {
        playlistsLoading,
        searchQuery,
        newFormShowing,
        showPlaylistPopover,
        allPlaylists,
        currentPlaylistsLoading,
        modifyingPlaylist,
        pinnedCount,
    } = useValues(logic)
    const { setSearchQuery, setNewFormShowing, setShowPlaylistPopover, addToPlaylist, removeFromPlaylist } =
        useActions(logic)
    return (
        <IconWithCount showZero={false} count={pinnedCount}>
            <Popover
                visible={showPlaylistPopover}
                onClickOutside={() => setShowPlaylistPopover(false)}
                actionable
                overlay={
                    <div className="deprecated-space-y-1 w-100">
                        <div className="shrink-0 deprecated-space-y-1">
                            {newFormShowing ? (
                                <Form
                                    formKey="newPlaylist"
                                    logic={playlistPopoverLogic}
                                    props={{ sessionRecordingId, playerKey: logicProps.playerKey }}
                                    enableFormOnSubmit
                                    className="deprecated-space-y-1"
                                >
                                    <LemonField name="name">
                                        <LemonInput placeholder="Collection name" fullWidth />
                                    </LemonField>
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
                                        placeholder="Search collections..."
                                        value={searchQuery}
                                        onChange={setSearchQuery}
                                        fullWidth
                                    />
                                    <LemonButton fullWidth icon={<IconPlus />} onClick={() => setNewFormShowing(true)}>
                                        New collection
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
                                            onClick={() => {
                                                if (
                                                    setPinnedInCurrentPlaylist &&
                                                    playlist.short_id === currentPlaylistId
                                                ) {
                                                    return setPinnedInCurrentPlaylist(!selected)
                                                }

                                                !selected ? addToPlaylist(playlist) : removeFromPlaylist(playlist)
                                            }}
                                        >
                                            {playlist.name || playlist.derived_name}
                                        </LemonButton>

                                        <LemonButton
                                            icon={<IconOpenInNew />}
                                            to={urls.replayPlaylist(playlist.short_id)}
                                            targetBlank
                                        />
                                    </div>
                                ))}
                            </div>
                        ) : playlistsLoading ? (
                            <LemonSkeleton className="my-2 h-4" repeat={3} />
                        ) : (
                            <div className="p-2 text-center text-secondary">No collections found</div>
                        )}
                    </div>
                }
            >
                <LemonButton
                    icon={<IconPin />}
                    active={showPlaylistPopover}
                    onClick={() => setShowPlaylistPopover(!showPlaylistPopover)}
                    sideIcon={null}
                    {...buttonProps}
                />
            </Popover>
        </IconWithCount>
    )
}
