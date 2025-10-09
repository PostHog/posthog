import snappy from 'snappy-wasm'

// Initialize snappy-wasm
let snappyInitialized = false
let snappyInstance: typeof snappy | null = null

async function initSnappy(): Promise<void> {
    if (snappyInitialized && snappyInstance) {
        return
    }
    snappyInstance = await snappy
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

        if (!snappyInstance) {
            throw new Error('Snappy not initialized')
        }

        // Decompress the data
        const decompressed = snappyInstance.uncompress(compressedData)

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
