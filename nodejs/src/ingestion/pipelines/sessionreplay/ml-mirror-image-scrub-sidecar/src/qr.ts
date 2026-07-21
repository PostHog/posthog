/**
 * QR / barcode detection via zxing-wasm (pure wasm, no native deps). Machine-decodable codes are a
 * PII-carrier class the face/text detectors can't see — a TOTP provisioning QR or a ticket barcode
 * survives selective redaction at full fidelity — so detected codes get the same solid fill as text.
 * zxing only reports codes it can decode, which is the right bar: a code too degraded to decode is
 * also too degraded to leak.
 */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { prepareZXingModule, readBarcodes } from 'zxing-wasm/reader'

import { type Box } from './geometry.ts'
import { type Src } from './src-image.ts'

// zxing-wasm's default loader fetches its .wasm from a CDN on first use; hand it the binary that
// shipped in node_modules instead, so the worker needs no runtime egress and always runs the build
// the lockfile pinned. createRequire over import.meta so jest's CJS transform can load this module;
// cwd-based resolution matches the package's existing cwd-relative model paths (WORKDIR /code/app).
const wasmFile = createRequire(`${process.cwd()}/`).resolve('zxing-wasm/reader/zxing_reader.wasm')
const wasmBytes = readFileSync(wasmFile)
prepareZXingModule({
    overrides: {
        wasmBinary: wasmBytes.buffer.slice(wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength),
    },
})

const PAD = 0.15 // expand each hit so quiet zones / clipped modules are covered

export async function detectCodes(src: Src): Promise<Box[]> {
    const { data, W, H } = src
    // zxing takes RGBA ImageData; expand the shared raw RGB in one pass.
    const rgba = new Uint8ClampedArray(W * H * 4)
    for (let i = 0, o = 0; i < data.length; i += 3, o += 4) {
        rgba[o] = data[i]
        rgba[o + 1] = data[i + 1]
        rgba[o + 2] = data[i + 2]
        rgba[o + 3] = 255
    }
    // Structural ImageData (zxing dispatches on width/height/data); Node has no ImageData class, so
    // colorSpace only exists to satisfy the DOM type.
    const imageData = { data: rgba, width: W, height: H, colorSpace: 'srgb' } as ImageData
    const results = await readBarcodes(imageData, { tryHarder: true, maxNumberOfSymbols: 32 })

    const boxes: Box[] = []
    for (const r of results) {
        const p = r.position
        const xs = [p.topLeft.x, p.topRight.x, p.bottomLeft.x, p.bottomRight.x]
        const ys = [p.topLeft.y, p.topRight.y, p.bottomLeft.y, p.bottomRight.y]
        const minX = Math.min(...xs)
        const maxX = Math.max(...xs)
        const minY = Math.min(...ys)
        const maxY = Math.max(...ys)
        const px = (maxX - minX) * PAD
        const py = (maxY - minY) * PAD
        const left = Math.max(0, Math.round(minX - px))
        const top = Math.max(0, Math.round(minY - py))
        const right = Math.min(W, Math.round(maxX + px))
        const bottom = Math.min(H, Math.round(maxY + py))
        if (right - left >= 2 && bottom - top >= 2) {
            boxes.push({ left, top, width: right - left, height: bottom - top })
        }
    }
    return boxes
}
