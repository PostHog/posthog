import { router } from 'kea-router'
import api from 'lib/api'
import { ExpandableConfig } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from 'react'
import { urls } from 'scenes/urls'

import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'

export const THUMB_SIZE = 15
export const THUMB_OFFSET = THUMB_SIZE / 2

export type ReactInteractEvent = ReactMouseEvent<HTMLDivElement, MouseEvent> | ReactTouchEvent<HTMLDivElement>
export type InteractEvent = MouseEvent | TouchEvent

export function isTouchEvent(
    event: ReactInteractEvent | InteractEvent
): event is ReactTouchEvent<HTMLDivElement> | TouchEvent {
    return 'touches' in event
}

export function isMouseEvent(
    event: ReactInteractEvent | InteractEvent
): event is ReactMouseEvent<HTMLDivElement> | MouseEvent {
    return 'clientX' in event
}

export const getXPos = (event: ReactInteractEvent | InteractEvent): number => {
    if (isTouchEvent(event)) {
        return event?.touches?.[0]?.pageX ?? event?.changedTouches?.[0]?.pageX // x coordinates are in changedTouches on touchend
    }
    if (isMouseEvent(event)) {
        return event?.clientX
    }
    return 0
}

// Determines whether a given PlayerList row should be expanded or not.
//
// Checks if the row should be expanded depending on the expandable prop that was passed into the component,
// and if it's undeterminable, defaults to the component's local state. This logic is copied over from
// LemonTable and reappropriated for session recordings.
export function getRowExpandedState<T extends Record<string, any>>(
    record: T,
    recordIndex: number,
    expandable?: ExpandableConfig<T>,
    isRowExpandedLocal: boolean = false
): boolean {
    return (
        Number(!!expandable && (!expandable.rowExpandable || expandable.rowExpandable(record, recordIndex))) > 0 &&
        (!expandable?.isRowExpanded || expandable?.isRowExpanded?.(record, recordIndex) === -1
            ? isRowExpandedLocal
            : !!expandable?.isRowExpanded?.(record, recordIndex))
    )
}

export async function addRecordingToPlaylist(
    playlistId: SessionRecordingPlaylistType['short_id'],
    sessionRecordingId: SessionRecordingType['id'],
    silent = false
): Promise<void> {
    await api.recordings.addRecordingToPlaylist(playlistId, sessionRecordingId)
    if (!silent) {
        lemonToast.success('Recording added to playlist', {
            button: {
                label: 'View playlist',
                action: () => router.actions.push(urls.replayPlaylist(playlistId)),
            },
        })
    }
}

export async function removeRecordingFromPlaylist(
    playlistId: SessionRecordingPlaylistType['short_id'],
    sessionRecordingId: SessionRecordingType['id'],
    silent = false
): Promise<void> {
    await api.recordings.removeRecordingFromPlaylist(playlistId, sessionRecordingId)
    if (!silent) {
        lemonToast.success('Recording removed from playlist')
    }
}

export async function deleteRecording(recordingId: SessionRecordingType['id'], silent = false): Promise<void> {
    await api.recordings.delete(recordingId)
    if (!silent) {
        lemonToast.success('Recording deleted')
    }
}
