import { CANVAS_CHANNEL } from '../host/canvasProtocol'

/** The frame of the canvas being edited. One canvas is edited at a time, so a document query finds it. */
export function canvasEditorFrame(): HTMLIFrameElement | null {
    return document.querySelector<HTMLIFrameElement>('iframe[data-canvas-source-editor]')
}

/** Posts one message of the edit protocol to the canvas being edited. */
export function postToCanvasEditor(message: Record<string, unknown>): void {
    // The sandbox has an opaque origin, so no narrower target origin matches it.
    canvasEditorFrame()?.contentWindow?.postMessage({ channel: CANVAS_CHANNEL, ...message }, '*')
}
