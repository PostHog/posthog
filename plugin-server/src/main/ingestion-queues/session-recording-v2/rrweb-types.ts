import { RRWebEvent } from '~/src/types'

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

export function isClick(event: RRWebEvent): boolean {
    return (
        event.type === RRWebEventType.IncrementalSnapshot &&
        event.data?.source === RRWebEventSource.MouseInteraction &&
        [
            MouseInteractions.Click,
            MouseInteractions.DblClick,
            MouseInteractions.TouchEnd,
            MouseInteractions.ContextMenu, // right click
        ].includes(event.data?.type || -1)
    )
}

export function isKeypress(event: RRWebEvent): boolean {
    return event.type === RRWebEventType.IncrementalSnapshot && event.data?.source === RRWebEventSource.Input
}
