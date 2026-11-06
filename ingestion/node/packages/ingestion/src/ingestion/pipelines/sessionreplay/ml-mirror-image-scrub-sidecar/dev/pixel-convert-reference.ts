/**
 * The TypeScript loops that src/pixel-convert.ts replaced, as they ran at each call site. They are
 * the reference that the Rust conversions must match bit for bit (src/pixel-convert.test.ts), and
 * the baseline that dev/pixel-convert-bench.ts times them against. The only change from the call
 * sites is that the destination and the statistics come in as arguments.
 */

/** dbnet.ts: BGR planes with the statistics applied in plane order. */
export function dbnetChwTs(data: Uint8Array, chw: Float32Array, mean: readonly number[], std: readonly number[]): void {
    const plane = chw.length / 3
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = (data[i + 2] / 255 - mean[0]) / std[0]
        chw[plane + p] = (data[i + 1] / 255 - mean[1]) / std[1]
        chw[2 * plane + p] = (data[i] / 255 - mean[2]) / std[2]
    }
}

/** yunet.ts: BGR planes with the byte values unchanged. */
export function yunetChwTs(data: Uint8Array, chw: Float32Array): void {
    const plane = chw.length / 3
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = data[i + 2] // B
        chw[plane + p] = data[i + 1] // G
        chw[2 * plane + p] = data[i] // R
    }
}

/** safety.ts: RGB planes with the byte values unchanged. */
export function safetyChwTs(data: Uint8Array, chw: Float32Array): void {
    const plane = chw.length / 3
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = data[i]
        chw[plane + p] = data[i + 1]
        chw[2 * plane + p] = data[i + 2]
    }
}

/** qr.ts: RGBA with every pixel opaque. */
export function qrRgbaTs(data: Uint8Array, rgba: Uint8ClampedArray): void {
    for (let i = 0, o = 0; i < data.length; i += 3, o += 4) {
        rgba[o] = data[i]
        rgba[o + 1] = data[i + 1]
        rgba[o + 2] = data[i + 2]
        rgba[o + 3] = 255
    }
}
