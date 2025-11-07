export type DecompressionMode = 'worker' | 'yielding' | 'blocking'

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
let currentConfig: { mode?: string; posthog?: any } | null = null

export function getDecompressionWorkerManager(
    mode?: string | DecompressionMode,
    posthog?: any
): DecompressionWorkerManager {
    const configChanged = currentConfig && (currentConfig.mode !== mode || currentConfig.posthog !== posthog)

    if (configChanged) {
        terminateDecompressionWorker()
    }

    if (!workerManager) {
        workerManager = new DecompressionWorkerManager()
        currentConfig = { mode, posthog }
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
