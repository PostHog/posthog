import type { PostHog } from 'posthog-js'
import snappyInit, { decompress_raw } from 'snappy-wasm'

import type { DecompressionRequest, DecompressionResponse } from './decompressionWorker'
import { yieldToMain } from './yield-scheduler'

interface PendingRequest {
    resolve: (data: Uint8Array) => void
    reject: (error: Error) => void
    startTime: number
    dataSize: number
    isParallel?: boolean
}

interface DecompressionStats {
    totalTime: number
    count: number
    totalSize: number
}

export type DecompressionMode = 'worker' | 'yielding' | 'blocking' | 'worker_and_yielding'

export function normalizeMode(mode?: string | boolean): DecompressionMode {
    if (mode === 'worker' || mode === 'yielding' || mode === 'worker_and_yielding' || mode === 'blocking') {
        return mode
    }
    return 'worker'
}

export class DecompressionWorkerManager {
    private readonly readyPromise: Promise<void>
    private snappyInitialized = false
    private worker: Worker | null = null
    private messageId = 0
    private pendingRequests = new Map<number, PendingRequest>()
    private stats: DecompressionStats = { totalTime: 0, count: 0, totalSize: 0 }
    private readonly mode: DecompressionMode
    private isColdStart = true
    private workerInitFailed = false

    constructor(
        mode?: string | DecompressionMode,
        private readonly posthog?: PostHog
    ) {
        this.mode = normalizeMode(mode)
        this.readyPromise =
            this.mode === 'worker' || this.mode === 'worker_and_yielding' ? this.initWorker() : this.initSnappy()
    }

    private getErrorMessage(error: unknown): string {
        return error instanceof Error ? error.message : 'Unknown error'
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

                this.updateStats(
                    totalDuration,
                    pending.dataSize,
                    undefined,
                    workerDecompressDuration,
                    pending.isParallel
                )

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
            console.error(
                '[DecompressionWorkerManager] Failed to initialize worker, will fallback to main thread:',
                error
            )
            this.workerInitFailed = true
            this.worker = null
            await this.initSnappy()
            if (this.posthog) {
                this.posthog.capture('replay_worker_init_failed', {
                    error: this.getErrorMessage(error),
                })
            }
        }
    }

    private async initSnappy(): Promise<void> {
        if (this.snappyInitialized) {
            return
        }
        await snappyInit()
        this.snappyInitialized = true
    }

    async decompress(compressedData: Uint8Array, metadata?: { isParallel?: boolean }): Promise<Uint8Array> {
        await this.readyPromise

        if (this.shouldUseWorker()) {
            return this.decompressWithFallback(compressedData, metadata)
        }
        return this.decompressMainThread(compressedData, metadata)
    }

    private shouldUseWorker(): boolean {
        return (
            (this.mode === 'worker' || this.mode === 'worker_and_yielding') &&
            this.worker !== null &&
            !this.workerInitFailed
        )
    }

    private async decompressWithFallback(
        compressedData: Uint8Array,
        metadata?: { isParallel?: boolean }
    ): Promise<Uint8Array> {
        try {
            return await this.decompressWithWorker(compressedData, metadata)
        } catch (error) {
            this.reportWorkerFailure(error, compressedData.length, metadata?.isParallel)
            return await this.decompressMainThread(compressedData, metadata)
        }
    }

    private reportWorkerFailure(error: unknown, dataSize: number, isParallel?: boolean): void {
        console.warn('[DecompressionWorkerManager] Worker decompression failed, falling back to main thread:', error)
        if (this.posthog) {
            this.posthog.capture('replay_worker_decompression_failed', {
                error: this.getErrorMessage(error),
                dataSize,
                isParallel,
            })
        }
    }

    private async decompressWithWorker(
        compressedData: Uint8Array,
        metadata?: { isParallel?: boolean }
    ): Promise<Uint8Array> {
        const id = this.messageId++
        const startTime = performance.now()

        return new Promise<Uint8Array>((resolve, reject) => {
            // Timeout safeguard: if worker doesn't respond, reject and fallback
            const DECOMPRESSION_TIMEOUT_MS = 10000
            const timeout = setTimeout(() => {
                const pending = this.pendingRequests.get(id)
                if (pending) {
                    this.pendingRequests.delete(id)
                    console.error('[DecompressionWorkerManager] Worker decompression timeout', {
                        id,
                        dataSize: compressedData.length,
                        isParallel: metadata?.isParallel,
                        timeoutMs: DECOMPRESSION_TIMEOUT_MS,
                    })
                    reject(new Error('Worker decompression timeout'))
                }
            }, DECOMPRESSION_TIMEOUT_MS)

            this.pendingRequests.set(id, {
                resolve: (data) => {
                    clearTimeout(timeout)
                    resolve(data)
                },
                reject: (error) => {
                    clearTimeout(timeout)
                    reject(error)
                },
                startTime,
                dataSize: compressedData.length,
                isParallel: metadata?.isParallel,
            })

            const message: DecompressionRequest = {
                id,
                compressedData,
            }

            try {
                this.worker!.postMessage(message, { transfer: [compressedData.buffer] })
            } catch (error) {
                clearTimeout(timeout)
                this.pendingRequests.delete(id)
                reject(error instanceof Error ? error : new Error(this.getErrorMessage(error)))
            }
        })
    }

    private async decompressMainThread(
        compressedData: Uint8Array,
        metadata?: { isParallel?: boolean }
    ): Promise<Uint8Array> {
        const startTime = performance.now()
        const dataSize = compressedData.length

        try {
            let yieldDuration = 0
            if (this.mode === 'yielding' || this.mode === 'worker_and_yielding') {
                const yieldStart = performance.now()
                await yieldToMain()
                yieldDuration = performance.now() - yieldStart
            }

            const decompressStart = performance.now()
            const result = decompress_raw(compressedData)
            const decompressDuration = performance.now() - decompressStart

            const totalDuration = performance.now() - startTime
            this.updateStats(totalDuration, dataSize, yieldDuration, decompressDuration, metadata?.isParallel)
            return result
        } catch (error) {
            console.error('Decompression error:', error)
            throw error instanceof Error ? error : new Error('Unknown decompression error')
        }
    }

    private updateStats(
        duration: number,
        dataSize: number,
        yieldDuration?: number,
        decompressDuration?: number,
        isParallel?: boolean
    ): void {
        this.stats.totalTime += duration
        this.stats.count += 1
        this.stats.totalSize += dataSize
        const isColdStart = this.isColdStart
        if (this.isColdStart) {
            this.isColdStart = false
        }
        this.reportTiming(duration, dataSize, isColdStart, yieldDuration, decompressDuration, isParallel)
    }

    private reportTiming(
        durationMs: number,
        sizeBytes: number,
        isColdStart: boolean,
        yieldDuration?: number,
        decompressDuration?: number,
        isParallel?: boolean
    ): void {
        if (!this.posthog) {
            return
        }

        const properties: Record<string, any> = {
            method: this.mode,
            duration_ms: durationMs,
            size_bytes: sizeBytes,
            is_cold_start: isColdStart,
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

        if (isParallel !== undefined) {
            properties.is_parallel = isParallel
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

/**
 * Pre-warm the WASM decompression module.
 * Call this during app initialization to avoid cold start penalty.
 * Safe to call multiple times - will only initialize once.
 */
export function preWarmDecompression(): void {
    // Initialize WASM module in background
    // Don't await - let it warm up while app loads
    snappyInit().catch((error) => {
        console.error('[DecompressionWorkerManager] Failed to pre-warm WASM:', error)
    })
}
