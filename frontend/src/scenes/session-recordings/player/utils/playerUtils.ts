import { router } from 'kea-router'
import { MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from 'react'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
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

export async function addRecordingToPlaylist(
    playlistId: SessionRecordingPlaylistType['short_id'],
    sessionRecordingId: SessionRecordingType['id'],
    silent = false
): Promise<void> {
    await api.recordings.addRecordingToPlaylist(playlistId, sessionRecordingId)
    if (!silent) {
        lemonToast.success('Recording added to collection', {
            button: {
                label: 'View collection',
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
        lemonToast.success('Recording removed from collection')
    }
}

export async function deleteRecording(recordingId: SessionRecordingType['id'], silent = false): Promise<void> {
    await api.recordings.delete(recordingId)
    if (!silent) {
        lemonToast.success('Recording deleted')
    }
}
