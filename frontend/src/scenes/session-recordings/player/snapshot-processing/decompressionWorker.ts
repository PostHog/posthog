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

        let decompressed: Uint8Array

        try {
            // Try direct decompression (Python snappy.decompress equivalent)
            decompressed = decompress_raw(compressedData)
        } catch {
            // If that fails, try skipping varint prefix (Node.js snappy.compressSync format)
            let offset = 0
            while (offset < compressedData.length) {
                const byte = compressedData[offset++]
                if ((byte & 0x80) === 0) {
                    break
                }
            }

            const dataWithoutPrefix = compressedData.slice(offset)
            decompressed = decompress_raw(dataWithoutPrefix)
        }

        // Send the result back to the main thread
        const response: DecompressionResponse = {
            id,
            decompressedData: decompressed,
        }
        self.postMessage(response)
    } catch (error) {
        console.error('Decompression error:', error)
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
