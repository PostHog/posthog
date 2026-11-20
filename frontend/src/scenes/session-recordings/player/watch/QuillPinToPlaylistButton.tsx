import { useActions, useValues } from 'kea'

import { IconMinusSmall, IconPlus, IconPlusSmall } from '@posthog/icons'
import {
    Badge,
    Button,
    CheckboxIndicator,
    Input,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Skeleton,
    Spinner,
} from '@posthog/quill'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { playlistPopoverLogic } from 'scenes/session-recordings/player/playlist-popover/playlistPopoverLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/** Quill sibling of `PinToPlaylistButton`: adds the recording to collections from the watch panel title row. */
export function QuillPinToPlaylistButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
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
        newPlaylist,
        isNewPlaylistSubmitting,
    } = useValues(logic)
    const {
        setSearchQuery,
        setNewFormShowing,
        setShowPlaylistPopover,
        addToPlaylist,
        removeFromPlaylist,
        setNewPlaylistValue,
        submitNewPlaylist,
    } = useActions(logic)

    const label = logicProps.pinned ? 'Remove from collection' : 'Add to collection'

    if (logicProps.setPinned && !logicProps.pinned) {
        return (
            <Button
                variant="secondary"
                onClick={() => logicProps.setPinned?.(true)}
                tooltip={label}
                data-attr="pin-to-this-list"
            >
                <IconPlusSmall />
                {label}
            </Button>
        )
    }

    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )

    return (
        <Popover open={showPlaylistPopover} onOpenChange={setShowPlaylistPopover}>
            <PopoverTrigger
                render={
                    <Button
                        variant="secondary"
                        tooltip={label}
                        disabledReason={editDisabledReason ?? undefined}
                        data-attr="player-collection-popover-toggle"
                    />
                }
            >
                {logicProps.pinned ? <IconMinusSmall /> : <IconPlusSmall />}
                {label}
                {pinnedCount > 0 && <Badge>{pinnedCount}</Badge>}
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-0">
                <div className="flex flex-col gap-1 p-1">
                    {newFormShowing ? (
                        <form
                            className="flex flex-col gap-1"
                            onSubmit={(event) => {
                                event.preventDefault()
                                submitNewPlaylist()
                            }}
                        >
                            <Input
                                size="sm"
                                placeholder="Collection name"
                                value={newPlaylist.name}
                                onChange={(event) => setNewPlaylistValue('name', event.target.value)}
                                autoFocus
                            />
                            <div className="flex items-center justify-end gap-1">
                                <Button
                                    size="sm"
                                    onClick={() => setNewFormShowing(false)}
                                    data-attr="player-collection-new-cancel"
                                >
                                    Cancel
                                </Button>
                                <Button
                                    size="sm"
                                    variant="primary"
                                    type="submit"
                                    loading={isNewPlaylistSubmitting}
                                    disabledReason={newPlaylist.name ? undefined : 'Give the collection a name'}
                                    data-attr="player-collection-new-create"
                                >
                                    <IconPlus />
                                    Create and add
                                </Button>
                            </div>
                        </form>
                    ) : (
                        <>
                            <Input
                                type="search"
                                size="sm"
                                placeholder="Search collections…"
                                value={searchQuery}
                                onChange={(event) => setSearchQuery(event.target.value)}
                                autoFocus
                            />
                            <Button
                                size="row"
                                left
                                className="w-full"
                                onClick={() => setNewFormShowing(true)}
                                data-attr="player-collection-new-open"
                            >
                                <IconPlus />
                                New collection
                            </Button>
                        </>
                    )}
                </div>
                <Separator />
                <div className="max-h-60 overflow-y-auto p-1">
                    {allPlaylists.length ? (
                        allPlaylists.map(({ selected, playlist }) => {
                            const modifying =
                                currentPlaylistsLoading && modifyingPlaylist?.short_id === playlist.short_id
                            return (
                                <div key={playlist.short_id} className="flex items-center gap-1">
                                    <Button
                                        size="row"
                                        left
                                        className="flex-1 min-w-0"
                                        onClick={() => {
                                            if (logicProps.setPinned && playlist.short_id === currentPlaylistId) {
                                                logicProps.setPinned(!selected)
                                                return
                                            }
                                            if (selected) {
                                                removeFromPlaylist(playlist)
                                            } else {
                                                addToPlaylist(playlist)
                                            }
                                        }}
                                        data-attr="player-collection-toggle-item"
                                    >
                                        {modifying ? <Spinner /> : <CheckboxIndicator checked={selected} size="sm" />}
                                        <span className="truncate">{playlist.name || playlist.derived_name}</span>
                                    </Button>
                                    <Button
                                        size="icon-sm"
                                        aria-label="Open collection"
                                        tooltip="Open collection"
                                        render={
                                            <LinkPrimitive
                                                to={urls.replayPlaylist(playlist.short_id)}
                                                target="_blank"
                                            />
                                        }
                                        data-attr="player-collection-open"
                                    >
                                        <IconOpenInNew />
                                    </Button>
                                </div>
                            )
                        })
                    ) : playlistsLoading ? (
                        <div className="flex flex-col gap-2 p-2">
                            <Skeleton className="h-4" />
                            <Skeleton className="h-4" />
                            <Skeleton className="h-4" />
                        </div>
                    ) : (
                        <div className="p-2 text-center text-sm text-muted-foreground">No collections found</div>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    )
}
