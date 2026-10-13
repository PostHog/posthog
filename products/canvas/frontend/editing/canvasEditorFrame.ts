import { CANVAS_CHANNEL } from '../host/canvasProtocol'

/** The frame of the canvas being edited. One canvas is edited at a time, so a document query finds it. */
export function canvasEditorFrame(): HTMLIFrameElement | null {
    return document.querySelector<HTMLIFrameElement>('iframe[data-canvas-source-editor]')
}

const bridges = new WeakMap<HTMLIFrameElement, (message: unknown) => void>()

export function connectCanvasEditor(frame: HTMLIFrameElement, post: (message: unknown) => void): () => void {
    bridges.set(frame, post)
    return () => {
        bridges.delete(frame)
    }
}

export function postToCanvasEditor(message: Record<string, unknown>): void {
    const frame = canvasEditorFrame()
    if (frame) {
        bridges.get(frame)?.({ channel: CANVAS_CHANNEL, ...message })
    }
}
