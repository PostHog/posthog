import { type Box } from '../src/geometry.ts'

export function mulberry32(seed: number): () => number {
    let a = seed >>> 0
    return () => {
        a = (a + 0x6d2b79f5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

/** The fraction of `gt` ([left, top, right, bottom)) that the union of `boxes` covers. */
export function coverage(boxes: Box[], gt: [number, number, number, number]): number {
    const [x0, y0, x1, y1] = gt
    const W = Math.max(1, x1 - x0)
    const H = Math.max(1, y1 - y0)
    const mask = new Uint8Array(W * H)
    for (const b of boxes) {
        const l = Math.max(x0, b.left)
        const t = Math.max(y0, b.top)
        const r = Math.min(x1, b.left + b.width)
        const bt = Math.min(y1, b.top + b.height)
        for (let y = t; y < bt; y++) {
            mask.fill(1, (y - y0) * W + (l - x0), (y - y0) * W + (r - x0))
        }
    }
    let n = 0
    for (const v of mask) {
        n += v
    }
    return n / (W * H)
}
