import { ApiError } from 'lib/api-error'

import { terminalCreate, terminalDestroy } from '~/generated/core/api'
import type { TerminalSandboxApi, TerminalSandboxSizeEnumApi } from '~/generated/core/api.schemas'

export class ModalTerminalRuntime {
    private socket: WebSocket | null = null
    private request: Promise<TerminalSandboxApi> | null = null
    private stopping: Promise<void> | null = null
    private stopped = false
    private columns = 80
    private rows = 24
    private output = ''
    private decoder = new TextDecoder()

    constructor(
        private projectId: string,
        private onOutput: (bytes: Uint8Array) => void,
        private onClose: (message: string) => void
    ) {}

    async start(size: TerminalSandboxSizeEnumApi): Promise<TerminalSandboxSizeEnumApi> {
        this.request = terminalCreate(this.projectId, { sandbox_size: size })
        const session = await this.request
        if (this.stopped) {
            return session.sandbox_size
        }
        const url = new URL('/terminal', session.url)
        url.protocol = 'wss:'
        url.searchParams.set('_modal_connect_token', session.token)
        const socket = new WebSocket(url)
        this.socket = socket
        socket.binaryType = 'arraybuffer'
        await new Promise<void>((resolve, reject) => {
            let connected = false
            const timeout = setTimeout(() => {
                reject(new Error('The sandbox connection timed out. Try reconnecting.'))
                socket.close()
            }, 30_000)
            socket.onopen = () => {
                clearTimeout(timeout)
                if (this.stopped) {
                    socket.close()
                    resolve()
                    return
                }
                connected = true
                this.resize(this.columns, this.rows)
                resolve()
            }
            socket.onmessage = ({ data }: MessageEvent<ArrayBuffer>) => {
                if (this.stopped) {
                    return
                }
                const bytes = new Uint8Array(data)
                this.output = (this.output + this.decoder.decode(bytes, { stream: true })).slice(-20_000)
                this.onOutput(bytes)
            }
            socket.onerror = () => {
                clearTimeout(timeout)
                reject(new Error('Could not connect to the Modal sandbox. Try reconnecting.'))
                socket.close()
            }
            socket.onclose = ({ code }) => {
                clearTimeout(timeout)
                if (code === 4409) {
                    this.request = null
                }
                if (!connected) {
                    reject(new Error('The sandbox connection closed before it was ready.'))
                }
                if (!this.stopped) {
                    this.onClose(
                        code === 4409
                            ? 'This sandbox is open in another tab. Close that terminal before reconnecting.'
                            : 'The sandbox disconnected. Reconnect to resume using its files.'
                    )
                }
            }
        })
        return session.sandbox_size
    }

    write(data: string): void {
        while (data && this.socket?.readyState === WebSocket.OPEN) {
            let length = Math.min(data.length, 8000)
            if (length < data.length && /[\uD800-\uDBFF]/.test(data[length - 1])) {
                length--
            }
            this.socket.send(JSON.stringify(data.slice(0, length)))
            data = data.slice(length)
        }
    }

    resize(columns: number, rows: number): void {
        this.columns = columns
        this.rows = rows
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ columns, rows }))
        }
    }

    read(): string {
        return this.output
    }

    disconnect(): void {
        this.stopped = true
        this.socket?.close()
    }

    stop(): Promise<void> {
        if (this.stopping) {
            return this.stopping
        }
        this.stopped = true
        this.socket?.close()
        this.stopping = (async () => {
            const session = await this.request?.catch(() => null)
            if (session) {
                try {
                    await terminalDestroy(this.projectId, session.id)
                } catch (error) {
                    // A 404 means another tab replaced this session, so no sandbox is left to destroy.
                    if (!(error instanceof ApiError && error.status === 404)) {
                        throw error
                    }
                }
            }
        })().catch((error) => {
            this.stopping = null
            throw error
        })
        return this.stopping
    }
}
