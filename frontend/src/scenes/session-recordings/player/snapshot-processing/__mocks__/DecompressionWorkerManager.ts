export class DecompressionWorkerManager {
    private mockStats = {
        worker: { totalTime: 0, count: 0, totalSize: 0 },
        mainThread: { totalTime: 0, count: 0, totalSize: 0 },
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        // Mock implementation for tests - just return the data as-is
        // In real tests that need actual decompression, they can mock this method
        this.mockStats.mainThread.count++
        this.mockStats.mainThread.totalSize += compressedData.length
        this.mockStats.mainThread.totalTime += 1
        return compressedData
    }

    async decompressBatch(compressedBlocks: Uint8Array[]): Promise<Uint8Array[]> {
        return Promise.all(compressedBlocks.map((block) => this.decompress(block)))
    }

    getStats(): typeof this.mockStats {
        return { ...this.mockStats }
    }

    terminate(): void {
        // No-op for tests
    }
}

let workerManager: DecompressionWorkerManager | null = null
let currentConfig: { useWorker?: boolean; posthog?: any } | null = null

export function getDecompressionWorkerManager(useWorker?: boolean, posthog?: any): DecompressionWorkerManager {
    const configChanged = currentConfig && (currentConfig.useWorker !== useWorker || currentConfig.posthog !== posthog)

    if (configChanged) {
        terminateDecompressionWorker()
    }

    if (!workerManager) {
        workerManager = new DecompressionWorkerManager()
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
