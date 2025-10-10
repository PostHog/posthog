import snappy from 'snappy'

export class DecompressionWorkerManager {
    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        // Synchronous decompression for tests
        // Convert Uint8Array to Buffer for snappy
        const buffer = Buffer.from(compressedData)
        const result = await snappy.uncompress(buffer)
        // Convert Buffer to Uint8Array to match the real implementation
        return new Uint8Array(result)
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
