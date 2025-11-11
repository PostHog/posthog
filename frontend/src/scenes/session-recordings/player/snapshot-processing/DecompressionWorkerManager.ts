import type { PostHog } from 'posthog-js'
import snappyInit, { decompress_raw } from 'snappy-wasm'

import type { DecompressionRequest, DecompressionResponse } from './decompressionWorker'
import { yieldToMain } from './yield-scheduler'

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

export type DecompressionMode = 'worker' | 'yielding' | 'blocking'

export function normalizeMode(mode?: string | boolean): DecompressionMode {
    if (mode === 'worker' || mode === 'yielding') {
        return mode
    }
    return 'blocking'
}

export class DecompressionWorkerManager {
    private readonly readyPromise: Promise<void>
    private snappyInitialized = false
    private worker: Worker | null = null
    private messageId = 0
    private pendingRequests = new Map<number, PendingRequest>()
    private stats: DecompressionStats = { totalTime: 0, count: 0, totalSize: 0 }
    private readonly mode: DecompressionMode

    constructor(
        mode?: string | DecompressionMode,
        private readonly posthog?: PostHog
    ) {
        this.mode = normalizeMode(mode)
        this.readyPromise = this.mode === 'worker' ? this.initWorker() : this.initSnappy()
    }

    private async initWorker(): Promise<void> {
        try {
            this.worker = new Worker('/static/decompressionWorker.js', { type: 'module' })

            const readyPromise = Promise.race([
                new Promise<void>((resolve) => {
                    const handler = (event: MessageEvent): void => {
                        if (event.data.type === 'ready') {
                            this.worker?.removeEventListener('message', handler)
                            resolve()
                        }
                    }
                    this.worker?.addEventListener('message', handler)
                }),
                new Promise<void>((_, reject) =>
                    setTimeout(() => reject(new Error('Worker initialization timeout')), 5000)
                ),
            ])

            this.worker.addEventListener('message', (event: MessageEvent) => {
                const data = event.data

                if ('type' in data && data.type === 'ready') {
                    return
                }

                const { id, decompressedData, error, workerDecompressDuration } = data as DecompressionResponse

                const pending = this.pendingRequests.get(id)
                if (!pending) {
                    return
                }

                this.pendingRequests.delete(id)

                const totalDuration = performance.now() - pending.startTime

                this.updateStats(totalDuration, pending.dataSize, undefined, workerDecompressDuration)

                if (error || !decompressedData) {
                    pending.reject(new Error(error || 'Decompression failed'))
                } else {
                    pending.resolve(decompressedData)
                }
            })

            this.worker.addEventListener('error', (error) => {
                console.error('[DecompressionWorkerManager] Worker error:', error)
                this.pendingRequests.forEach((pending) => {
                    pending.reject(new Error(`Worker error: ${error.message}`))
                })
                this.pendingRequests.clear()
            })

            await readyPromise
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

        if (this.mode === 'worker' && this.worker) {
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

            this.worker!.postMessage(message, { transfer: [compressedData.buffer] })
        })
    }

    private async decompressMainThread(compressedData: Uint8Array): Promise<Uint8Array> {
        const startTime = performance.now()
        const dataSize = compressedData.length

        try {
            let yieldDuration = 0
            if (this.mode === 'yielding') {
                const yieldStart = performance.now()
                await yieldToMain()
                yieldDuration = performance.now() - yieldStart
            }

            const decompressStart = performance.now()
            const result = decompress_raw(compressedData)
            const decompressDuration = performance.now() - decompressStart

            const totalDuration = performance.now() - startTime
            this.updateStats(totalDuration, dataSize, yieldDuration, decompressDuration)
            return result
        } catch (error) {
            console.error('Decompression error:', error)
            throw error instanceof Error ? error : new Error('Unknown decompression error')
        }
    }

    private updateStats(duration: number, dataSize: number, yieldDuration?: number, decompressDuration?: number): void {
        this.stats.totalTime += duration
        this.stats.count += 1
        this.stats.totalSize += dataSize
        this.reportTiming(duration, dataSize, yieldDuration, decompressDuration)
    }

    private reportTiming(
        durationMs: number,
        sizeBytes: number,
        yieldDuration?: number,
        decompressDuration?: number
    ): void {
        if (!this.posthog) {
            return
        }

        const properties: Record<string, any> = {
            method: this.mode,
            duration_ms: durationMs,
            size_bytes: sizeBytes,
            aggregate_total_time_ms: this.stats.totalTime,
            aggregate_count: this.stats.count,
            aggregate_total_size_bytes: this.stats.totalSize,
            aggregate_avg_time_ms: this.stats.count > 0 ? this.stats.totalTime / this.stats.count : 0,
        }

        if (yieldDuration !== undefined) {
            properties.yield_duration_ms = yieldDuration
        }

        if (decompressDuration !== undefined) {
            properties.decompress_duration_ms = decompressDuration
            properties.overhead_duration_ms = durationMs - decompressDuration - (yieldDuration || 0)
        }

        this.posthog.capture('replay_decompression_timing', properties)
    }

    getStats(): DecompressionStats {
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
let currentConfig: { mode?: DecompressionMode; posthog?: PostHog } | null = null

export function getDecompressionWorkerManager(
    mode?: string | DecompressionMode,
    posthog?: PostHog
): DecompressionWorkerManager {
    const normalizedMode = normalizeMode(mode)
    const configChanged = currentConfig && (currentConfig.mode !== normalizedMode || currentConfig.posthog !== posthog)

    if (configChanged) {
        terminateDecompressionWorker()
    }

    if (!workerManager) {
        workerManager = new DecompressionWorkerManager(mode, posthog)
        currentConfig = { mode: normalizedMode, posthog }
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
