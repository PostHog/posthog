export class DecompressionWorkerManager {
    private mockStats = { totalTime: 0, count: 0, totalSize: 0 }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        this.mockStats.count++
        this.mockStats.totalSize += compressedData.length
        this.mockStats.totalTime += 1
        return compressedData
    }

    getStats(): typeof this.mockStats {
        return { ...this.mockStats }
    }

    terminate(): void {
        // No-op for tests
    }
}

let workerManager: DecompressionWorkerManager | null = null
let currentPosthog: any | undefined

export function getDecompressionWorkerManager(posthog?: any): DecompressionWorkerManager {
    const configChanged = currentPosthog !== posthog

    if (configChanged && workerManager) {
        terminateDecompressionWorker()
    }

    if (!workerManager) {
        workerManager = new DecompressionWorkerManager()
        currentPosthog = posthog
    }
    return workerManager
}

export function terminateDecompressionWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
    currentPosthog = undefined
}
