export class DecompressionWorkerManager {
    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        return compressedData
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
