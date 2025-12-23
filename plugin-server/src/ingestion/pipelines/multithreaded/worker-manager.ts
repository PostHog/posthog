import { MessageChannel, MessagePort, Worker } from 'worker_threads'

import { WorkerResult, WorkerToMainMessage } from './serializable'

export interface WorkerConfig {
    [key: string]: any
}

export interface WorkerHandle {
    worker: Worker
    port: MessagePort
    pendingResults: Map<string, (result: WorkerResult) => void>
    flushResolve?: () => void
}

export class WorkerManager {
    private workers: WorkerHandle[] = []
    private ready: Promise<void>

    constructor(
        private numWorkers: number,
        private workerPath: string,
        private workerConfig: WorkerConfig
    ) {
        this.ready = this.initializeWorkers()
    }

    private async initializeWorkers(): Promise<void> {
        const readyPromises: Promise<void>[] = []

        for (let i = 0; i < this.numWorkers; i++) {
            const { port1, port2 } = new MessageChannel()

            const worker = new Worker(this.workerPath, {
                workerData: {
                    config: this.workerConfig,
                    port: port2,
                },
                transferList: [port2],
                execArgv: ['-r', 'ts-node/register/transpile-only'],
            })

            const handle: WorkerHandle = {
                worker,
                port: port1,
                pendingResults: new Map(),
            }

            port1.on('message', (msg: WorkerToMainMessage) => {
                this.handleWorkerMessage(handle, msg)
            })

            readyPromises.push(
                new Promise<void>((resolve) => {
                    const onReady = (msg: WorkerToMainMessage) => {
                        if (msg.type === 'ready') {
                            port1.off('message', onReady)
                            resolve()
                        }
                    }
                    port1.on('message', onReady)
                })
            )

            this.workers.push(handle)
        }

        await Promise.all(readyPromises)
    }

    private handleWorkerMessage(handle: WorkerHandle, msg: WorkerToMainMessage): void {
        switch (msg.type) {
            case 'result': {
                const resolve = handle.pendingResults.get(msg.result.correlationId)
                if (resolve) {
                    handle.pendingResults.delete(msg.result.correlationId)
                    resolve(msg.result)
                }
                break
            }
            case 'flush_complete': {
                handle.flushResolve?.()
                handle.flushResolve = undefined
                break
            }
            case 'error': {
                // TODO: Log error, potentially restart worker
                break
            }
        }
    }

    /**
     * Send event to appropriate worker based on shard key
     */
    async sendEvent(shardKey: string, correlationId: string, data: Uint8Array): Promise<WorkerResult> {
        await this.ready

        const shardIndex = this.hashToShard(shardKey)
        const handle = this.workers[shardIndex]

        return new Promise((resolve) => {
            handle.pendingResults.set(correlationId, resolve)
            handle.port.postMessage({ type: 'event', correlationId, data })
        })
    }

    /**
     * Flush all workers - wait for pending events to complete
     */
    async flush(): Promise<void> {
        await this.ready

        const flushPromises = this.workers.map(
            (handle) =>
                new Promise<void>((resolve) => {
                    handle.flushResolve = resolve
                    handle.port.postMessage({ type: 'flush' })
                })
        )

        await Promise.all(flushPromises)
    }

    private hashToShard(key: string): number {
        let hash = 0
        for (let i = 0; i < key.length; i++) {
            hash = (hash << 5) - hash + key.charCodeAt(i)
            hash |= 0
        }
        return Math.abs(hash) % this.workers.length
    }

    async shutdown(): Promise<void> {
        for (const handle of this.workers) {
            handle.port.postMessage({ type: 'shutdown' })
            await handle.worker.terminate()
        }
        this.workers = []
    }
}
