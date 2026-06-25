/** Gaussian-blur media/canvas `data:image/*` URIs (with a size cap), run as deferred jobs. */
import sharp from 'sharp'

import { BlurJob } from './config'

// Cap the longest side to bound output bytes, then Gaussian-blur to destroy readable
// detail (drawn text, faces). The blur — not the resize — is what removes PII, so the
// cap stays generous; a tiny downscale alone left blurry-but-still-legible thumbnails.
const MAX_DIMENSION = 100
const BLUR_SIGMA = 8
// Fallback when the Gaussian blur fails on an odd input: an aggressive downsample still
// destroys most detail (and beats dropping the image to a blank placeholder).
const DOWNSAMPLE_TARGET = 16

/** A 1×1 transparent PNG: the fail-safe stand-in dropped in before (and if) the real blur lands. */
export const BLANK_PNG_BASE64 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
export const BLANK_IMAGE_DATA_URI = `data:image/png;base64,${BLANK_PNG_BASE64}`

export function isImageDataUri(s: string): boolean {
    return s.startsWith('data:image/')
}

/** Gaussian-blur a base64 image data URI to a size-capped PNG, or null if it can't. */
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
    // Prefer a size-capped Gaussian blur; if it fails on an odd input, fall back to an
    // aggressive downsample (still destroys most detail). Give up only if both fail.
    try {
        const out = await sharp(bytes)
            // Cap the longest side (never enlarge), preserving aspect ratio.
            .resize(MAX_DIMENSION, MAX_DIMENSION, { fit: 'inside', withoutEnlargement: true })
            // True Gaussian blur — this is what makes drawn text/faces unreadable.
            .blur(BLUR_SIGMA)
            .png()
            .toBuffer()
        return `data:image/png;base64,${out.toString('base64')}`
    } catch {
        // Gaussian path failed — fall through to the downsample fallback below.
    }
    try {
        const out = await sharp(bytes).resize(DOWNSAMPLE_TARGET, DOWNSAMPLE_TARGET, { fit: 'inside' }).png().toBuffer()
        return `data:image/png;base64,${out.toString('base64')}`
    } catch {
        return null
    }
}

/** Run deferred blur jobs, applying each blurred result in place on success. */
export async function runBlurJobs(jobs: BlurJob[] | undefined): Promise<void> {
    if (!jobs || jobs.length === 0) {
        return
    }
    await Promise.all(
        jobs.map(async (job) => {
            const blurred = await blurImageDataUri(job.dataUri)
            if (blurred !== null) {
                job.apply(blurred)
            }
        })
    )
}
