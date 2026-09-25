/**
 * The pixel layout conversions that build the model inputs and zxing's RGBA frame, run in the
 * replay-anonymizer Rust addon (rust/replay-anonymizer-node/src/pixels.rs). The caller allocates
 * each destination and the addon borrows both typed arrays in place, so no pixel data is copied
 * across the boundary.
 */
import { createRequire } from 'node:module'
import { resolve } from 'node:path'

export type PlaneOrder = 'rgb' | 'bgr'
export type PerPlane = readonly [number, number, number]

interface PixelConvert {
    /** Interleaved RGB bytes to channel-major float planes with the byte values unchanged. */
    rgbToChw(rgb: Uint8Array, chw: Float32Array, order: PlaneOrder): void
    /** Interleaved RGB bytes to channel-major float planes of `(value / 255 - mean) / std`, with
     *  `mean` and `std` in plane order. Each value is the one that expression gives in JS when it is
     *  stored into a Float32Array. */
    rgbToNormalizedChw(rgb: Uint8Array, chw: Float32Array, order: PlaneOrder, mean: PerPlane, std: PerPlane): void
    /** Interleaved RGB bytes to interleaved RGBA bytes with every pixel opaque. */
    rgbToRgba(rgb: Uint8Array, rgba: Uint8ClampedArray): void
}

const FUNCTIONS = ['rgbToChw', 'rgbToNormalizedChw', 'rgbToRgba'] as const

// Resolved against the working directory like the models, because the image and the dev scripts
// both run from the package root. It is made absolute because jest's createRequire resolves a
// relative path from the parent of the directory that it is given.
const ADDON_PATH = resolve('native/replay-anonymizer.node')

function loadPixelConvert(): PixelConvert {
    let addon: Partial<PixelConvert>
    try {
        addon = createRequire(ADDON_PATH)(ADDON_PATH) as Partial<PixelConvert>
    } catch (error) {
        throw new Error(`cannot load the native addon at ${ADDON_PATH}; build it with \`npm run build:native\``, {
            cause: error,
        })
    }
    const missing = FUNCTIONS.filter((name) => typeof addon[name] !== 'function')
    if (missing.length > 0) {
        throw new Error(
            `the native addon at ${ADDON_PATH} has no ${missing.join(', ')}; rebuild it with \`npm run build:native\``
        )
    }
    return addon as PixelConvert
}

// Loaded at import so that a missing or stale addon fails worker startup, which fails the pool and
// the image build's smoke test, rather than the first scrub.
export const { rgbToChw, rgbToNormalizedChw, rgbToRgba } = loadPixelConvert()
