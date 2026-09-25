/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Pixel layout conversion cost: each TypeScript loop that src/pixel-convert.ts replaced against the
 * Rust addon, at the sizes production converts, and whether the two give the same bytes.
 *
 *   tsx dev/pixel-convert-bench.ts [--iterations N] [--warmup N]
 *
 * Needs the addon in native/ (`npm run build:native`). Every case converts the same pseudo-random
 * frame with both implementations, alternating call by call so that clock and thermal drift land on
 * both, and reports the median call. Both write into a destination allocated once, so the times
 * leave out the allocation, which production makes the same way either side of the change.
 */
import { arch, cpus } from 'node:os'

import { type PerPlane, rgbToChw, rgbToNormalizedChw, rgbToRgba } from '../src/pixel-convert.ts'
import { mulberry32 } from './bench-common.ts'
import { dbnetChwTs, qrRgbaTs, safetyChwTs, yunetChwTs } from './pixel-convert-reference.ts'

const IMAGENET_MEAN: PerPlane = [0.485, 0.456, 0.406]
const IMAGENET_STD: PerPlane = [0.229, 0.224, 0.225]

type Destination = Float32Array | Uint8ClampedArray

// Methods rather than function properties, so that each case can narrow `out` to its own array type.
interface Case {
    conversion: string
    width: number
    height: number
    allocate(pixels: number): Destination
    ts(rgb: Buffer, out: Destination): void
    rust(rgb: Buffer, out: Destination): void
}

const planes = (pixels: number): Float32Array => new Float32Array(3 * pixels)
const rgbaBytes = (pixels: number): Uint8ClampedArray => new Uint8ClampedArray(4 * pixels)

const dbnet = {
    conversion: 'dbnet (normalized BGR)',
    allocate: planes,
    ts: (rgb: Buffer, chw: Float32Array) => dbnetChwTs(rgb, chw, IMAGENET_MEAN, IMAGENET_STD),
    rust: (rgb: Buffer, chw: Float32Array) => rgbToNormalizedChw(rgb, chw, 'bgr', IMAGENET_MEAN, IMAGENET_STD),
}
const qr = {
    conversion: 'qr (RGBA)',
    allocate: rgbaBytes,
    ts: (rgb: Buffer, rgba: Uint8ClampedArray) => qrRgbaTs(rgb, rgba),
    rust: (rgb: Buffer, rgba: Uint8ClampedArray) => rgbToRgba(rgb, rgba),
}

// The text canvases are two that the scale plan hands DBNet, YuNet takes a fixed 640x640 input,
// safety.ts resizes to 224x224, and the code frames are two sizes that zxing reads.
const CASES: Case[] = [
    { ...dbnet, width: 640, height: 384 },
    { ...dbnet, width: 928, height: 576 },
    {
        conversion: 'yunet (BGR)',
        width: 640,
        height: 640,
        allocate: planes,
        ts: (rgb, chw: Float32Array) => yunetChwTs(rgb, chw),
        rust: (rgb, chw: Float32Array) => rgbToChw(rgb, chw, 'bgr'),
    },
    {
        conversion: 'safety (RGB)',
        width: 224,
        height: 224,
        allocate: planes,
        ts: (rgb, chw: Float32Array) => safetyChwTs(rgb, chw),
        rust: (rgb, chw: Float32Array) => rgbToChw(rgb, chw, 'rgb'),
    },
    { ...qr, width: 638, height: 359 },
    { ...qr, width: 1181, height: 664 },
]

function arg(name: string): string | undefined {
    const i = process.argv.indexOf(`--${name}`)
    return i >= 0 ? process.argv[i + 1] : undefined
}

// A Buffer, like the raw output of sharp that production converts, so V8 compiles the TypeScript
// loops for the same receiver type that they see in production.
function randomRgb(pixels: number, seed: number): Buffer {
    const random = mulberry32(seed)
    const rgb = Buffer.alloc(3 * pixels)
    for (let i = 0; i < rgb.length; i++) {
        rgb[i] = random() * 256
    }
    return rgb
}

function timeMs(run: (rgb: Buffer, out: Destination) => void, rgb: Buffer, out: Destination): number {
    const start = performance.now()
    run(rgb, out)
    return performance.now() - start
}

function median(values: number[]): number {
    const sorted = [...values].sort((a, b) => a - b)
    const middle = sorted.length >> 1
    return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function main(): void {
    const iterations = Number(arg('iterations') ?? 200)
    const warmup = Number(arg('warmup') ?? 50)
    console.log(`node ${process.version} ${arch()} ${cpus()[0]?.model ?? 'unknown cpu'}`)
    console.log(`median of ${iterations} calls per implementation after ${warmup} warm-up calls\n`)
    console.log(
        'conversion              size        pixels    ts ms  rust ms  ts ns/px  rust ns/px  speedup  same bytes'
    )
    let mismatches = 0
    for (const [index, c] of CASES.entries()) {
        const pixels = c.width * c.height
        const rgb = randomRgb(pixels, index + 1)
        const tsOut = c.allocate(pixels)
        const rustOut = c.allocate(pixels)
        for (let i = 0; i < warmup; i++) {
            c.ts(rgb, tsOut)
            c.rust(rgb, rustOut)
        }
        const tsMs: number[] = []
        const rustMs: number[] = []
        for (let i = 0; i < iterations; i++) {
            tsMs.push(timeMs(c.ts, rgb, tsOut))
            rustMs.push(timeMs(c.rust, rgb, rustOut))
        }
        const same = Buffer.from(tsOut.buffer).equals(Buffer.from(rustOut.buffer))
        if (!same) {
            mismatches++
        }
        const [ts, rust] = [median(tsMs), median(rustMs)]
        console.log(
            [
                c.conversion.padEnd(22),
                `${c.width}x${c.height}`.padStart(9),
                String(pixels).padStart(9),
                ts.toFixed(3).padStart(8),
                rust.toFixed(3).padStart(8),
                ((ts * 1e6) / pixels).toFixed(2).padStart(9),
                ((rust * 1e6) / pixels).toFixed(2).padStart(11),
                `${(ts / rust).toFixed(1)}x`.padStart(8),
                (same ? 'yes' : 'NO').padStart(11),
            ].join(' ')
        )
    }
    if (mismatches > 0) {
        console.error(`\n${mismatches} of ${CASES.length} conversions gave different bytes`)
        process.exitCode = 1
    }
}

main()
