import type { PostHog } from 'posthog-js'
import snappyInit, { decompress_raw } from 'snappy-wasm'

import type { DecompressionRequest, DecompressionResponse } from './decompressionWorker'

interface PendingRequest {
    resolve: (data: Uint8Array) => void
    reject: (error: Error) => void
    startTime: number
    dataSize: number
}

interface DecompressionStats {
    totalTime: number
    count: number
    totalSize: number
}

export class DecompressionWorkerManager {
    private readonly readyPromise: Promise<void>
    private snappyInitialized = false
    private worker: Worker | null = null
    private messageId = 0
    private pendingRequests = new Map<number, PendingRequest>()
    private stats: { worker: DecompressionStats; mainThread: DecompressionStats } = {
        worker: { totalTime: 0, count: 0, totalSize: 0 },
        mainThread: { totalTime: 0, count: 0, totalSize: 0 },
    }

    constructor(
        private readonly useWorker: boolean = false,
        private readonly posthog?: PostHog
    ) {
        this.readyPromise = this.useWorker ? this.initWorker() : this.initSnappy()
    }

    private async initWorker(): Promise<void> {
        try {
            this.worker = new Worker('/static/decompressionWorker.js', { type: 'module' })

            this.worker.addEventListener('message', (event: MessageEvent<DecompressionResponse>) => {
                const { id, decompressedData, error } = event.data

                const pending = this.pendingRequests.get(id)
                if (!pending) {
                    return
                }

                this.pendingRequests.delete(id)

                const duration = performance.now() - pending.startTime
                this.updateStats('worker', duration, pending.dataSize)

                if (error || !decompressedData) {
                    pending.reject(new Error(error || 'Decompression failed'))
                } else {
                    pending.resolve(decompressedData)
                }
            })

            this.worker.addEventListener('error', (error) => {
                console.error('[DecompressionWorkerManager] Worker error:', error)
            })

            await new Promise<void>((resolve) => {
                const handler = (event: MessageEvent): void => {
                    if (event.data.type === 'ready') {
                        this.worker?.removeEventListener('message', handler)
                        resolve()
                    }
                }
                this.worker?.addEventListener('message', handler)
            })
        } catch (error) {
            console.error('[DecompressionWorkerManager] Failed to initialize worker:', error)
            throw error
        }
    }

    private async initSnappy(): Promise<void> {
        if (this.snappyInitialized) {
            return
        }
        await snappyInit()
        this.snappyInitialized = true
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        await this.readyPromise

        if (this.useWorker && this.worker) {
            return this.decompressWithWorker(compressedData)
        }
        return this.decompressMainThread(compressedData)
    }

    private async decompressWithWorker(compressedData: Uint8Array): Promise<Uint8Array> {
        const id = this.messageId++
        const startTime = performance.now()

        return new Promise<Uint8Array>((resolve, reject) => {
            this.pendingRequests.set(id, {
                resolve,
                reject,
                startTime,
                dataSize: compressedData.length,
            })

            const message: DecompressionRequest = {
                id,
                compressedData,
            }

            this.worker!.postMessage(message, [compressedData.buffer])
        })
    }

    private async decompressMainThread(compressedData: Uint8Array): Promise<Uint8Array> {
        const startTime = performance.now()
        const dataSize = compressedData.length

        try {
            const result = decompress_raw(compressedData)
            const duration = performance.now() - startTime
            this.updateStats('main-thread', duration, dataSize)
            return result
        } catch (error) {
            console.error('Decompression error:', error)
            throw error instanceof Error ? error : new Error('Unknown decompression error')
        }
    }

    private getStatsForMethod(method: 'worker' | 'main-thread'): DecompressionStats {
        return method === 'worker' ? this.stats.worker : this.stats.mainThread
    }

    private updateStats(method: 'worker' | 'main-thread', duration: number, dataSize: number): void {
        const stats = this.getStatsForMethod(method)
        stats.totalTime += duration
        stats.count += 1
        stats.totalSize += dataSize
        this.reportTiming(method, duration, dataSize)
    }

    private reportTiming(method: 'worker' | 'main-thread', durationMs: number, sizeBytes: number): void {
        if (!this.posthog) {
            return
        }

        const stats = this.getStatsForMethod(method)

        this.posthog.capture('replay_decompression_timing', {
            method,
            duration_ms: durationMs,
            size_bytes: sizeBytes,
            aggregate_total_time_ms: stats.totalTime,
            aggregate_count: stats.count,
            aggregate_total_size_bytes: stats.totalSize,
            aggregate_avg_time_ms: stats.count > 0 ? stats.totalTime / stats.count : 0,
        })
    }

    getStats(): typeof this.stats {
        return { ...this.stats }
    }

    terminate(): void {
        if (this.worker) {
            this.worker.terminate()
            this.worker = null
        }

        this.pendingRequests.forEach((pending) => {
            pending.reject(new Error('Worker terminated'))
        })
        this.pendingRequests.clear()
    }
}

let workerManager: DecompressionWorkerManager | null = null
let currentConfig: { useWorker?: boolean; posthog?: PostHog } | null = null

export function getDecompressionWorkerManager(useWorker?: boolean, posthog?: PostHog): DecompressionWorkerManager {
    const configChanged = currentConfig && (currentConfig.useWorker !== useWorker || currentConfig.posthog !== posthog)

    if (configChanged) {
        terminateDecompressionWorker()
    }

    if (!workerManager) {
        workerManager = new DecompressionWorkerManager(useWorker, posthog)
        currentConfig = { useWorker, posthog }
    }
    return workerManager
}

export function terminateDecompressionWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
    currentConfig = null
}
