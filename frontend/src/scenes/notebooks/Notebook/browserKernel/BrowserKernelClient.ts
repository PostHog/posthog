import {
    BROWSER_KERNEL_PRELOADED_PACKAGES,
    BrowserKernelEnvelope,
    BrowserKernelFrame,
    BrowserKernelFramePage,
    BrowserKernelPage,
    BrowserKernelRequest,
    BrowserKernelResponse,
    BrowserKernelRunPayload,
    BrowserKernelStagedInput,
    PYODIDE_INDEX_URL,
} from './browserKernelProtocol'

// Pyodide downloads about 30 MB on a cold cache, so this allows for a slow connection.
const START_TIMEOUT_MS = 180_000

type DistributiveOmit<T, K extends keyof any> = T extends unknown ? Omit<T, K> : never

export class BrowserKernelClient {
    private worker: Worker
    private nextId = 1
    private pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>()
    private interruptView: Uint8Array | null = null
    private terminated = false
    readonly started: Promise<void>

    constructor(
        private onProgress: (message: string) => void,
        private onCrash: (message: string) => void
    ) {
        this.worker = new Worker('/static/notebookPythonWorker.js', { type: 'module', name: 'Notebook Python' })
        this.worker.onmessage = ({ data }: MessageEvent<BrowserKernelResponse>): void => this.receive(data)
        this.worker.onerror = (event): void => {
            event.preventDefault()
            this.fail(event.message || 'The browser kernel stopped unexpectedly.')
        }
        // Only a cross-origin isolated page can share memory with the worker. Without it a stop has
        // no way to reach a running cell, so it restarts the kernel instead.
        const interruptBuffer =
            typeof SharedArrayBuffer !== 'undefined' && globalThis.crossOriginIsolated ? new SharedArrayBuffer(1) : null
        this.interruptView = interruptBuffer ? new Uint8Array(interruptBuffer) : null
        this.started = withTimeout(
            this.request({
                type: 'init',
                indexURL: PYODIDE_INDEX_URL,
                packages: BROWSER_KERNEL_PRELOADED_PACKAGES,
                interruptBuffer,
            }),
            START_TIMEOUT_MS,
            'Python took too long to load. Check your connection and restart the kernel.'
        ).then(() => undefined)
    }

    get canInterrupt(): boolean {
        return !!this.interruptView
    }

    run(payload: BrowserKernelRunPayload, staged: BrowserKernelStagedInput[]): Promise<BrowserKernelEnvelope> {
        return this.request({ type: 'run', payload, staged })
    }

    hasInput(key: string): Promise<boolean> {
        return this.request({ type: 'hasInput', key })
    }

    page(resultId: string, offset: number, limit: number): Promise<BrowserKernelPage | { missing: true }> {
        return this.request({ type: 'page', resultId, offset, limit })
    }

    readFrame(name: string, offset: number, limit: number): Promise<BrowserKernelFramePage | { missing: true }> {
        return this.request({ type: 'readFrame', name, offset, limit })
    }

    frames(): Promise<BrowserKernelFrame[]> {
        return this.request({ type: 'frames' })
    }

    /** Ask the running cell to stop. False when this page cannot interrupt, and only a restart stops it. */
    interrupt(): boolean {
        if (!this.interruptView) {
            return false
        }
        // 2 is SIGINT, which Pyodide raises as KeyboardInterrupt in the running cell.
        this.interruptView[0] = 2
        return true
    }

    terminate(reason = 'The browser kernel stopped.'): void {
        if (this.terminated) {
            return
        }
        this.terminated = true
        this.worker.terminate()
        this.rejectAll(reason)
    }

    private request<T>(message: DistributiveOmit<BrowserKernelRequest, 'id'>): Promise<T> {
        if (this.terminated) {
            return Promise.reject(new Error('The browser kernel stopped. Start it again to run cells.'))
        }
        const id = this.nextId++
        return new Promise<T>((resolve, reject) => {
            this.pending.set(id, { resolve, reject })
            this.worker.postMessage({ ...message, id } as BrowserKernelRequest)
        })
    }

    private receive(data: BrowserKernelResponse): void {
        if (data.type === 'progress') {
            this.onProgress(data.message)
            return
        }
        const pending = this.pending.get(data.id)
        if (!pending) {
            return
        }
        this.pending.delete(data.id)
        if (data.type === 'result') {
            pending.resolve(data.value)
        } else {
            pending.reject(new Error(data.message))
        }
    }

    private fail(message: string): void {
        if (this.terminated) {
            return
        }
        this.terminate(message)
        this.onCrash(message)
    }

    private rejectAll(message: string): void {
        for (const { reject } of this.pending.values()) {
            reject(new Error(message))
        }
        this.pending.clear()
    }
}

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error(message)), ms)
        promise.then(
            (value) => {
                clearTimeout(timeout)
                resolve(value)
            },
            (error) => {
                clearTimeout(timeout)
                reject(error)
            }
        )
    })
}
