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
}

// Handle messages from the main thread
self.addEventListener('message', async (event: MessageEvent<DecompressionRequest>) => {
    const { id, compressedData } = event.data

    try {
        // Ensure snappy is initialized
        await initSnappy()

        // Decompress the data
        // decompress_raw returns Uint8Array directly from compressed Uint8Array
        const decompressed = decompress_raw(compressedData)

        // Send the result back to the main thread
        const response: DecompressionResponse = {
            id,
            decompressedData: decompressed,
        }
        self.postMessage(response)
    } catch (error) {
        // Send error back to the main thread
        const response: DecompressionResponse = {
            id,
            decompressedData: null,
            error: error instanceof Error ? error.message : 'Unknown error',
        }
        self.postMessage(response)
    }
})

// Send ready signal once the worker is loaded
self.postMessage({ type: 'ready' })
