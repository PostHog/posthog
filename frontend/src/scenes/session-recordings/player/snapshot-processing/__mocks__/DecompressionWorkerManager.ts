export class DecompressionWorkerManager {
    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        // Mock implementation for tests - just return the data as-is
        // In real tests that need actual decompression, they can mock this method
        return compressedData
    }

    async decompressBatch(compressedBlocks: Uint8Array[]): Promise<Uint8Array[]> {
        return Promise.all(compressedBlocks.map((block) => this.decompress(block)))
    }

    terminate(): void {
        // No-op for tests
    }
}

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
