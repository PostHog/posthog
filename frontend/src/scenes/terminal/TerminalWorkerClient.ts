import type { NinePServer } from './ninepServer'
import type { TerminalWorkerBoot, TerminalWorkerRequest, TerminalWorkerResponse } from './terminalWorkerProtocol'

export class TerminalWorkerClient {
    private worker: Worker
    private listeners = new Map<string, (byte: number) => void>()
    private disposed = false
    private rejectLoaded?: (error: Error) => void
    private timeout?: ReturnType<typeof setTimeout>
    readonly loaded: Promise<void>

    constructor(
        boot: TerminalWorkerBoot,
        server: NinePServer,
        private onError: (message: string) => void
    ) {
        this.worker = new Worker('/static/terminalWorker.js', { type: 'module', name: 'PostHog terminal' })
        this.loaded = new Promise((resolve, reject) => {
            this.rejectLoaded = reject
            this.timeout = setTimeout(() => this.fail('Terminal worker timed out. Restart the terminal.'), 60_000)
            this.worker.onmessage = ({ data }: MessageEvent<TerminalWorkerResponse>): void => {
                if (this.disposed) {
                    return
                }
                switch (data.type) {
                    case 'loaded':
                        clearTimeout(this.timeout)
                        this.rejectLoaded = undefined
                        resolve()
                        break
                    case 'serial':
                        for (const byte of data.bytes) {
                            this.listeners.get(`serial${data.port}-output-byte`)?.(byte)
                        }
                        break
                    case '9p':
                        server.handle(data.bytes, (bytes) => {
                            if (!this.disposed) {
                                this.send({ type: '9p', id: data.id, bytes }, [bytes.buffer])
                            }
                        })
                        break
                    case 'error':
                        this.fail(data.message)
                        break
                }
            }
            this.worker.onerror = (event): void => {
                event.preventDefault()
                this.fail('Terminal worker failed. Restart the terminal.')
            }
            this.worker.onmessageerror = (): void =>
                this.fail('Terminal worker connection failed. Restart the terminal.')
            this.send({ type: 'start', ...boot }, [boot.bios, boot.vgaBios, boot.kernel, boot.canvas])
        })
    }

    private fail(message: string): void {
        if (this.disposed) {
            return
        }
        this.rejectLoaded?.(new Error(message))
        this.dispose()
        this.onError(message)
    }

    send(message: TerminalWorkerRequest, transfer: Transferable[] = []): void {
        if (!this.disposed) {
            this.worker.postMessage(message, transfer)
        }
    }

    add_listener(event: string, callback: (byte: number) => void): void {
        this.listeners.set(event, callback)
    }

    serial0_send(data: string): void {
        this.serial_send_bytes(0, new TextEncoder().encode(data))
    }

    serial_send_bytes(port: number, bytes: Uint8Array): void {
        this.send({ type: 'serial', port, bytes })
    }

    keyboard_send_scancodes(codes: number[]): void {
        this.send({ type: 'keyboard', codes })
    }

    dispose(): void {
        if (this.disposed) {
            return
        }
        this.disposed = true
        clearTimeout(this.timeout)
        this.rejectLoaded?.(new DOMException('Terminal stopped', 'AbortError'))
        this.rejectLoaded = undefined
        this.listeners.clear()
        this.worker.terminate()
    }
}
