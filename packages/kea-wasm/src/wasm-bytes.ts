// Browser and bundler builds embed the module as base64, because kea must start synchronously
// when it is imported. The Node.js build replaces this file with wasm-bytes.node.ts.
import { wasmBase64 } from '../gen/wasm-base64.js'

export function loadWasmBytes(): Uint8Array {
    const binary = atob(wasmBase64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
    }
    return bytes
}
