import snappyInit, { decompress_raw } from 'snappy-wasm'

export class DecompressionWorkerManager {
    private readyPromise: Promise<void>
    private snappyInitialized = false

    constructor() {
        this.readyPromise = this.initSnappy()
    }

    private async initSnappy(): Promise<void> {
        if (this.snappyInitialized) {
            return
        }
        // Prevent multiple concurrent initializations
        if (!this.readyPromise) {
            this.readyPromise = snappyInit().then(() => {
                this.snappyInitialized = true
            })
        }
        await this.readyPromise
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        await this.readyPromise

        try {
            return decompress_raw(compressedData)
        } catch (error) {
            console.error('Decompression error:', error)
            throw error instanceof Error ? error : new Error('Unknown decompression error')
        }
    }

    terminate(): void {
        // No cleanup needed for direct snappy usage
    }
}

// Singleton instance
let workerManager: DecompressionWorkerManager | null = null

export function getDecompressionWorkerManager(): DecompressionWorkerManager {
    if (!workerManager) {
        workerManager = new DecompressionWorkerManager()
    }
    return workerManager
}

export function terminateDecompressionWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
}
