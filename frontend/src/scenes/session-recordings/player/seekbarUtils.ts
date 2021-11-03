import { MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from 'react'

export const THUMB_SIZE = 14
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

export const convertXToValue = (xPos: number, containerWidth: number, start: number, end: number): number => {
    return (xPos / containerWidth) * (end - start) + start
}
export const convertValueToX = (value: number, containerWidth: number, start: number, end: number): number => {
    return (containerWidth * (value - start)) / (end - start)
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
