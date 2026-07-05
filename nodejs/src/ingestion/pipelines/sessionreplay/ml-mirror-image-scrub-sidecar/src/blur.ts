// These params must stay in sync with nodejs/.../anonymize/blur.ts, or the mirror diverges from the inline anonymizer.
import sharp from 'sharp'

// One libvips thread per op and no cross-request cache, so N concurrent scrubs cost ~N threads (not N x CPU)
// and no shared cache: bounds sidecar CPU/RSS under the concurrency ceiling.
sharp.concurrency(1)
sharp.cache(false)

const DOWNSAMPLE_RATIO = 0.12
const BLUR_SIGMA = 2.34
const MAX_LONG_SIDE = 96
// Cap decoded pixels: compressed bytes expand many-fold in libvips, so this guards RSS, not input size.
const LIMIT_INPUT_PIXELS = 50_000_000

export class UndecodableImageError extends Error {}

function targetDims(w: number, h: number): [number, number] {
    const scale = Math.min(DOWNSAMPLE_RATIO, MAX_LONG_SIDE / Math.max(w, h))
    return [Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale))]
}

export async function blurOnly(input: Buffer): Promise<Buffer> {
    // Any libvips failure — bad header OR a corrupt/truncated body that fails mid-decode — is permanent for
    // these bytes, so map it all to UndecodableImageError (422/skip). A 500 here would poison the partition.
    try {
        const meta = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
        if (!meta.width || !meta.height) {
            throw new UndecodableImageError('image has invalid dimensions')
        }
        // Reject oversized images from the cheap header read, before the full-resolution decode allocates
        // ~4 bytes/pixel. (The decode enforces the same cap, but only after starting to allocate.)
        if (meta.width * meta.height > LIMIT_INPUT_PIXELS) {
            throw new UndecodableImageError('image exceeds the pixel limit')
        }
        const [tw, th] = targetDims(meta.width, meta.height)
        return await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
            .resize(tw, th, { fit: 'fill' })
            .blur(BLUR_SIGMA)
            .png()
            .toBuffer()
    } catch (e) {
        throw e instanceof UndecodableImageError ? e : new UndecodableImageError(String(e))
    }
}
