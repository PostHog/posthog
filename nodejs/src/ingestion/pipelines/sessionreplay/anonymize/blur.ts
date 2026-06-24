/** Downscale-blur media `data:image/*` URIs to a tiny PNG, run as deferred jobs. */
import sharp from 'sharp'

import { BlurJob } from './config'

const TARGET = 16

export function isImageDataUri(s: string): boolean {
    return s.startsWith('data:image/')
}

/** Downscale-blur a base64 image data URI to a tiny PNG, or null if it can't. */
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
    try {
        const bytes = Buffer.from(s.slice(comma + 1), 'base64')
        const out = await sharp(bytes)
            // fit: 'inside' scales the longest side to TARGET, preserving aspect.
            .resize(TARGET, TARGET, { fit: 'inside' })
            .png()
            .toBuffer()
        return `data:image/png;base64,${out.toString('base64')}`
    } catch {
        return null
    }
}

/** Run deferred blur jobs, replacing each placeholder with the blurred thumbnail on success. */
export async function runBlurJobs(jobs: BlurJob[] | undefined): Promise<void> {
    if (!jobs || jobs.length === 0) {
        return
    }
    await Promise.all(
        jobs.map(async (job) => {
            const blurred = await blurImageDataUri(job.dataUri)
            if (blurred !== null) {
                job.attrs[job.key] = blurred
            }
        })
    )
}
