import { CANVAS_CHANNEL, CanvasTheme } from './canvasProtocol'

const WRAPPER_ERROR_MESSAGE = 'The canvas frame could not load this canvas'

export function wrappedCanvasUrl(frameDocumentUrl: string, documentUrl: string, theme: CanvasTheme): string {
    const url = new URL(frameDocumentUrl)
    url.hash = new URLSearchParams({ src: documentUrl, theme }).toString()
    return url.href
}

/** A port belongs to one document, unlike an iframe's WindowProxy. */
export class CanvasDocumentBridge {
    private port: MessagePort | null = null
    private loads = 0

    constructor(
        private readonly iframe: HTMLIFrameElement,
        private readonly onMessage: (data: unknown) => void,
        private readonly onConnect: () => void,
        private readonly onWrapperError?: (message: string) => void
    ) {
        iframe.addEventListener('load', this.onLoad)
        window.addEventListener('message', this.onWindowMessage)
    }

    post = (message: unknown): void => {
        this.port?.postMessage(message)
    }

    setWrapperTheme = (theme: CanvasTheme): void => {
        // nosemgrep: wildcard-postmessage-configuration -- Opaque sandbox origin; the message carries only the theme.
        this.iframe.contentWindow?.postMessage({ channel: CANVAS_CHANNEL, type: 'set-theme', theme }, '*')
    }

    private onLoad = (): void => {
        this.loads += 1
        this.port?.close()
        this.port = null
        if (this.loads !== 1) {
            return
        }
        const { port1, port2 } = new MessageChannel()
        this.port = port1
        port1.onmessage = (event) => this.onMessage(event.data)
        // nosemgrep: wildcard-postmessage-configuration -- Opaque sandbox origin; this transfers only the first document's private port.
        this.iframe.contentWindow?.postMessage({ channel: CANVAS_CHANNEL, type: 'connect' }, '*', [port2])
        this.onConnect()
    }

    // The wrapper loads once, so the wrapper reports a canvas navigation with a "navigated" message.
    private onWindowMessage = (event: MessageEvent): void => {
        if (event.source !== this.iframe.contentWindow || event.data?.channel !== CANVAS_CHANNEL) {
            return
        }
        if (event.data.type === 'navigated') {
            this.port?.close()
            this.port = null
        } else if (event.data.type === 'wrapper-error') {
            this.onWrapperError?.(WRAPPER_ERROR_MESSAGE)
        }
    }

    close = (): void => {
        this.iframe.removeEventListener('load', this.onLoad)
        window.removeEventListener('message', this.onWindowMessage)
        this.port?.close()
        this.port = null
    }
}
