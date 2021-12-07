import { MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from 'react'
import { PlayerPosition, RecordingSegment } from '~/types'

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

// **********NOTE:*********** Update these to use the convertPlayerTimeToPlayerPosition etc.
export const convertXToPlayerPosition = (
    xValue: number,
    containerWidth: number,
    segments: RecordingSegment[],
    durationMs: number
): PlayerPosition => {
    const playerTime = (xValue / containerWidth) * durationMs
    let currentTime = 0
    for (const segment of segments) {
        if (currentTime + segment.durationMs > playerTime) {
            console.log('convertXToPlayerPosition', {
                windowId: segment.windowId,
                time: playerTime - currentTime,
            })
            return {
                windowId: segment.windowId,
                time: playerTime - currentTime + segment.startPlayerPosition.time,
            }
        } else {
            currentTime += segment.durationMs
        }
    }
    throw `X Value is outside player bounds: ${xValue}`
}

export const convertPlayerPositionToX = (
    playerPosition: PlayerPosition,
    containerWidth: number,
    segments: RecordingSegment[],
    durationMs: number
): number => {
    let currentTime = 0
    for (const segment of segments) {
        if (
            playerPosition.windowId === segment.windowId &&
            playerPosition.time >= segment.startPlayerPosition.time &&
            playerPosition.time <= segment.endPlayerPosition.time
        ) {
            currentTime += playerPosition.time - segment.startPlayerPosition.time
            break
        } else {
            currentTime += segment.durationMs
        }
    }
    return (currentTime / durationMs) * containerWidth
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
