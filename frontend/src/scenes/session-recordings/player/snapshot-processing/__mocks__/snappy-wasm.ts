// Mock implementation of snappy-wasm for testing
export default async function snappyInit(): Promise<void> {
    // No-op for tests
    return Promise.resolve()
}

export function decompress_raw(data: Uint8Array): Uint8Array {
    // In tests, just return the input data
    return data
}
