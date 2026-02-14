export const decompressSnappy = jest.fn(async (compressedData: Uint8Array): Promise<Uint8Array> => {
    return compressedData
})

export class DecompressionWorkerManager {
    processSnapshots = jest.fn(async (): Promise<{ snapshots: never[]; windowIdMappings: never[] }> => {
        throw new Error('Snapshot processing worker not available in tests')
    })

    snapshotWorkerAvailable = false

    terminate = jest.fn()
}

let workerManager: DecompressionWorkerManager | null = null

export const getDecompressionWorkerManager = jest.fn((posthog?: any): DecompressionWorkerManager | null => {
    if (!workerManager && posthog) {
        workerManager = new DecompressionWorkerManager()
    }
    return workerManager
})

export function terminateDecompressionWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
}

export function preWarmDecompression(): void {
    // No-op for tests
}
