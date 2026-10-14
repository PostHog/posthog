import { CANVAS_CHANNEL } from './canvasProtocol'

/** A port belongs to one document, unlike an iframe's WindowProxy. */
export class CanvasDocumentBridge {
    private port: MessagePort | null = null
    private loads = 0

    constructor(
        private readonly iframe: HTMLIFrameElement,
        private readonly onMessage: (data: unknown) => void,
        private readonly onConnect: () => void
    ) {
        iframe.addEventListener('load', this.onLoad)
    }

    post = (message: unknown): void => {
        this.port?.postMessage(message)
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

    close = (): void => {
        this.iframe.removeEventListener('load', this.onLoad)
        this.port?.close()
        this.port = null
    }
}
