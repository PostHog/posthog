/** Downsample + blur media/canvas images — scene stays legible, faces/text don't. Run deferred. */
import sharp from 'sharp'

import { BlurCache, BlurJob } from './config'

const DOWNSAMPLE_RATIO = 0.12
const BLUR_SIGMA = 2.34
const MAX_LONG_SIDE = 96

/** A 1×1 transparent PNG: the fail-safe stand-in dropped in before (and if) the real blur lands. */
export const BLANK_PNG_BASE64 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
export const BLANK_IMAGE_DATA_URI = `data:image/png;base64,${BLANK_PNG_BASE64}`

export function isImageDataUri(s: string): boolean {
    return s.startsWith('data:image/')
}

/** Scale to DOWNSAMPLE_RATIO, but never leave the long side above MAX_LONG_SIDE; floored at 1px. */
function targetDims(width: unknown, height: unknown): [number, number] {
    const w = typeof width === 'number' && width > 0 ? width : 1
    const h = typeof height === 'number' && height > 0 ? height : 1
    const scale = Math.min(DOWNSAMPLE_RATIO, MAX_LONG_SIDE / Math.max(w, h))
    return [Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale))]
}

/** Downsample a base64 image data URI to a fraction of its size + a blur, as a PNG; null if it can't. */
export async function blurImageDataUri(s: string): Promise<string | null> {
    if (!s.startsWith('data:')) {
        return null
    }
    const comma = s.indexOf(',')
    if (comma === -1) {
        return null
    }
    const meta = s.slice('data:'.length, comma)
    if (!meta.includes('base64') || !meta.startsWith('image/')) {
        return null
    }
    const bytes = Buffer.from(s.slice(comma + 1), 'base64')

    let tw: number, th: number
    try {
        const info = await sharp(bytes).metadata()
        ;[tw, th] = targetDims(info.width, info.height)
    } catch {
        return null // can't even read the header
    }
    // Primary: downsample + Gaussian blur.
    try {
        const out = await sharp(bytes).resize(tw, th, { fit: 'fill' }).blur(BLUR_SIGMA).png().toBuffer()
        return `data:image/png;base64,${out.toString('base64')}`
    } catch {
        // Blur failed on an odd input — fall through to a plain downsample (still de-identifies).
    }
    try {
        const out = await sharp(bytes).resize(tw, th, { fit: 'fill' }).png().toBuffer()
        return `data:image/png;base64,${out.toString('base64')}`
    } catch {
        return null
    }
}

/**
 * De-identify raw RGBA pixels: downsample to DOWNSAMPLE_RATIO + a blur, then scale back up to the
 * original W×H, preserving byte length (`4·W·H`) so it slots back into a `putImageData` ImageData.
 */
export async function pixelateRawRgba(base64: string, width: number, height: number): Promise<string | null> {
    try {
        const buf = Buffer.from(base64, 'base64')
        if (buf.length !== width * height * 4) {
            return null
        }
        const [sw, sh] = targetDims(width, height)
        const small = await sharp(buf, { raw: { width, height, channels: 4 } })
            .resize(sw, sh, { fit: 'fill' })
            .blur(BLUR_SIGMA)
            .ensureAlpha()
            .raw()
            .toBuffer()
        const out = await sharp(small, { raw: { width: sw, height: sh, channels: 4 } })
            .resize(width, height, { fit: 'fill' })
            .ensureAlpha()
            .raw()
            .toBuffer()
        return out.length === width * height * 4 ? out.toString('base64') : null
    } catch {
        return null
    }
}

/**
 * In-batch blur memo: within one Kafka message the same image often recurs thousands of times across
 * its rrweb events (a canvas redrawing one sprite, a repeated background), and both blur functions are
 * pure in their input. Sharing one settled Promise per distinct input collapses that fan-out to a
 * single sharp call. Neither producer rejects (both catch and return null), so a cached entry never
 * poisons its consumers. Scope is one Kafka message — the map is discarded when its blur jobs finish.
 */
export function memoizedBlur(
    cache: BlurCache | undefined,
    key: string,
    compute: () => Promise<string | null>
): Promise<string | null> {
    if (!cache) {
        return compute()
    }
    const existing = cache.get(key)
    if (existing !== undefined) {
        return existing
    }
    const pending = compute()
    cache.set(key, pending)
    return pending
}

/** Run deferred blur jobs concurrently. A job that throws is swallowed — the image was already
 *  blanked synchronously, so a failed enhancement degrades to the blank rather than leaking. */
export async function runBlurJobs(jobs: BlurJob[] | undefined): Promise<void> {
    if (!jobs || jobs.length === 0) {
        return
    }
    await Promise.all(
        jobs.map(async (job) => {
            try {
                await job()
            } catch {
                // image already neutralized synchronously; skip the enhancement
            }
        })
    )
}
