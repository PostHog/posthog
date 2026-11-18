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
import { rgbToRgba } from './pixel-convert.ts'
import { type Src, srcSharp } from './src-image.ts'

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

/** Reads the frame at `scale` of its size and returns boxes in frame coordinates. */
export async function detectCodes(src: Src, scale = 1): Promise<Box[]> {
    const width = Math.max(1, Math.round(src.W * scale))
    const height = Math.max(1, Math.round(src.H * scale))
    const data =
        width === src.W && height === src.H
            ? src.data
            : await srcSharp(src).resize(width, height, { fit: 'fill' }).raw().toBuffer()
    // zxing takes RGBA ImageData; expand the shared raw RGB in one pass.
    const rgba = new Uint8ClampedArray(width * height * 4)
    rgbToRgba(data, rgba)
    // Structural ImageData (zxing dispatches on width/height/data); Node has no ImageData class, so
    // colorSpace only exists to satisfy the DOM type.
    const imageData = { data: rgba, width, height, colorSpace: 'srgb' } as ImageData
    // tryHarder is the dominant cost here (roughly two thirds of this stage) and it stays on. It buys
    // nothing on crisp on-screen codes, where dropping it finds the same 13 of 15 in dev/make-code-corpus,
    // but a replay frame can hold a photographed code (a ticket on a phone, a webcam preview), and on
    // camera-degraded versions of that same set it finds 13 of 15 against 8 without. Restricting
    // formats is likewise a false economy: it drops a large Code128 that the full set decodes.
    const results = await readBarcodes(imageData, { tryHarder: true, maxNumberOfSymbols: 32 })

    const toFrameX = src.W / width
    const toFrameY = src.H / height
    const boxes: Box[] = []
    for (const r of results) {
        const p = r.position
        const xs = [p.topLeft.x, p.topRight.x, p.bottomLeft.x, p.bottomRight.x].map((x) => x * toFrameX)
        const ys = [p.topLeft.y, p.topRight.y, p.bottomLeft.y, p.bottomRight.y].map((y) => y * toFrameY)
        const minX = Math.min(...xs)
        const maxX = Math.max(...xs)
        const minY = Math.min(...ys)
        const maxY = Math.max(...ys)
        const px = (maxX - minX) * PAD
        const py = (maxY - minY) * PAD
        const left = Math.max(0, Math.floor(minX - px))
        const top = Math.max(0, Math.floor(minY - py))
        const right = Math.min(src.W, Math.ceil(maxX + px))
        const bottom = Math.min(src.H, Math.ceil(maxY + py))
        if (right - left >= 2 && bottom - top >= 2) {
            boxes.push({ left, top, width: right - left, height: bottom - top })
        }
    }
    return boxes
}
