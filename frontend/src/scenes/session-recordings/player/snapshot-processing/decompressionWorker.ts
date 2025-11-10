import snappyInit, { decompress_raw } from 'snappy-wasm'

// Initialize snappy-wasm
let snappyInitialized = false

async function initSnappy(): Promise<void> {
    if (snappyInitialized) {
        return
    }
    await snappyInit()
    snappyInitialized = true
}

export interface DecompressionRequest {
    id: number
    compressedData: Uint8Array
}

export interface DecompressionResponse {
    id: number
    decompressedData: Uint8Array | null
    error?: string
    workerDecompressDuration?: number
}

self.addEventListener('message', async (event: MessageEvent<DecompressionRequest>) => {
    const { id, compressedData } = event.data

    try {
        await initSnappy()
        const decompressStart = performance.now()
        const decompressed = decompress_raw(compressedData)
        const decompressDuration = performance.now() - decompressStart

        self.postMessage(
            {
                id,
                decompressedData: decompressed,
                workerDecompressDuration: decompressDuration,
            },
            { transfer: [decompressed.buffer] }
        )
    } catch (error) {
        console.error('Decompression error:', error)
        self.postMessage({
            id,
            decompressedData: null,
            error: error instanceof Error ? error.message : 'Unknown error',
        })
    }
})

// Send ready signal once the worker is loaded
self.postMessage({ type: 'ready' })
