// Node.js (and Jest) read the module from disk. A test runner loads kea once per test file, and a
// file read is much cheaper than parsing and decoding the embedded base64 string each time.
declare const require: (id: string) => any
declare const __dirname: string

export function loadWasmBytes(): Uint8Array {
    const fs = require('fs')
    const path = require('path')
    // dist/index.cjs.js has the module next to it. The TypeScript source finds it in gen/.
    for (const candidate of ['kea_wasm_engine_bg.wasm', '../gen/kea_wasm_engine_bg.wasm']) {
        const file = path.join(__dirname, candidate)
        if (fs.existsSync(file)) {
            return fs.readFileSync(file)
        }
    }
    throw new Error('[KEA] kea_wasm_engine_bg.wasm not found. Run packages/kea-wasm/build.mjs.')
}
