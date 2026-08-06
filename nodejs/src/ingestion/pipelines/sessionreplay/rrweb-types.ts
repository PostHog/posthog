import { SnapshotEvent } from './kafka/types'

export enum RRWebEventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
    Plugin = 6,
}

export enum RRWebEventSource {
    Mutation = 0,
    MouseMove = 1,
    MouseInteraction = 2,
    Scroll = 3,
    ViewportResize = 4,
    Input = 5,
    TouchMove = 6,
    MediaInteraction = 7,
    StyleSheetRule = 8,
    CanvasMutation = 9,
    Font = 10,
    Log = 11,
    Drag = 12,
    StyleDeclaration = 13,
    Selection = 14,
    AdoptedStyleSheet = 15,
}

export enum MouseInteractions {
    MouseUp = 0,
    MouseDown = 1,
    Click = 2,
    ContextMenu = 3,
    DblClick = 4,
    Focus = 5,
    Blur = 6,
    TouchStart = 7,
    TouchMove_Departed = 8,
    TouchEnd = 9,
    TouchCancel = 10,
}

const CLICK_TYPES = [
    MouseInteractions.Click,
    MouseInteractions.DblClick,
    MouseInteractions.TouchEnd,
    MouseInteractions.ContextMenu, // right click
]

const MOUSE_ACTIVITY_SOURCES = [
    RRWebEventSource.MouseInteraction,
    RRWebEventSource.MouseMove,
    RRWebEventSource.TouchMove,
]

export function isClick(inputEvent: SnapshotEvent): boolean {
    const event = inputEvent as { type?: number; data?: { source?: number; type?: number } } | undefined
    return (
        event?.type === RRWebEventType.IncrementalSnapshot &&
        event?.data?.source === RRWebEventSource.MouseInteraction &&
        CLICK_TYPES.includes(event?.data?.type ?? -1)
    )
}

export function isKeypress(inputEvent: SnapshotEvent): boolean {
    const event = inputEvent as { type?: number; data?: { source?: number } } | undefined
    return event?.type === RRWebEventType.IncrementalSnapshot && event?.data?.source === RRWebEventSource.Input
}

export function isMouseActivity(inputEvent: SnapshotEvent): boolean {
    const event = inputEvent as { type?: number; data?: { source?: number } } | undefined
    return (
        event?.type === RRWebEventType.IncrementalSnapshot && MOUSE_ACTIVITY_SOURCES.includes(event?.data?.source ?? -1)
    )
}

export function hrefFrom(inputEvent: SnapshotEvent): string | undefined {
    const event = inputEvent as { type?: number; data?: { href?: string; payload?: { href?: string } } } | undefined
    const metaHref = event?.data?.href?.trim?.()
    const customHref = event?.data?.payload?.href?.trim?.()
    return metaHref || customHref || undefined
}

// Constants for log levels
export enum ConsoleLogLevel {
    Info = 'info',
    Warn = 'warn',
    Error = 'error',
}
