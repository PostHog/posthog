import snappyInit, { decompress_raw } from 'snappy-wasm'

const DEBUG_VERSION_WORKER = 'v26'

console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Worker module is being loaded...`)
console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Imports loaded successfully`)

// Also post a message so it definitely appears in the manager's logs
self.postMessage({ type: 'debug', message: `Worker v${DEBUG_VERSION_WORKER} imports loaded` })

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
    // Log first 20 bytes to help diagnose format issues
    const firstBytes = Array.from(compressedData.slice(0, 20)).map(b => b.toString(16).padStart(2, '0')).join(' ')
    console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Received decompression request:`, {
        id,
        compressedDataSize: compressedData.length,
        firstBytes,
    })

    try {
        // Ensure snappy is initialized
        console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Initializing snappy...`)
        await initSnappy()
        console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Snappy initialized`)

        // Decompress the data
        // Try different approaches to figure out the format
        console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Starting decompression...`)

        let decompressed: Uint8Array

        // First, let's check what Python's snappy.decompress expects
        // Python's snappy library expects raw snappy format (no framing)
        // Since the backend uses Python's snappy.decompress successfully, the data IS valid snappy format

        // The issue: we're getting data that looks like it has a varint prefix
        // but snappy_wasm might be expecting pure raw format

        // Let's try: just pass the data as-is to Python snappy-compatible format
        console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Attempting direct decompression (Python snappy.decompress equivalent)`)

        try {
            // Import the Python-compatible Snappy bindings
            // snappy-wasm's decompress_raw should match Python's snappy.decompress
            decompressed = decompress_raw(compressedData)
            console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Direct decompression succeeded, size:`, decompressed.length)
        } catch (firstError) {
            console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Direct decompression failed, trying with varint skip...`)

            // If that fails, try skipping varint prefix (Node.js snappy.compressSync format)
            let offset = 0
            let shift = 0
            while (offset < compressedData.length) {
                const byte = compressedData[offset++]
                if ((byte & 0x80) === 0) {
                    break
                }
                shift += 7
            }

            console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Skipped ${offset} varint bytes, retrying decompression...`)
            const dataWithoutPrefix = compressedData.slice(offset)
            decompressed = decompress_raw(dataWithoutPrefix)
            console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Decompression with varint skip succeeded, size:`, decompressed.length)
        }

        // Send the result back to the main thread
        const response: DecompressionResponse = {
            id,
            decompressedData: decompressed,
        }
        console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Sending success response`)
        self.postMessage(response)
    } catch (error) {
        console.error(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Decompression error:`, error)
        // Send error back to the main thread
        const response: DecompressionResponse = {
            id,
            decompressedData: null,
            error: error instanceof Error ? error.message : 'Unknown error',
        }
        console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Sending error response`)
        self.postMessage(response)
    }
})

// Send ready signal once the worker is loaded
try {
    console.log(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Worker script loaded, sending ready signal`)
    self.postMessage({ type: 'ready' })
} catch (error) {
    console.error(`[DEBUG WORKER ${DEBUG_VERSION_WORKER}] Failed to send ready signal:`, error)
}
