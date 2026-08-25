// These params must stay in sync with rust/replay-anonymizer/src/blur.rs, or the mirror diverges from the inline anonymizer.
import { PermanentImageError, UndecodableImageError, inspectImage, sharpForImage } from './image-input.ts'

export { LIMIT_INPUT_PIXELS, UndecodableImageError } from './image-input.ts'

const DOWNSAMPLE_RATIO = 0.12
const BLUR_SIGMA = 2.34
const MAX_LONG_SIDE = 96
// 1x1 transparent PNG: the output substituted for an image the NSFW/gore gate rejects (see advancedScrub).
export const BLANK_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64'
)

function targetDims(w: number, h: number): [number, number] {
    const scale = Math.min(DOWNSAMPLE_RATIO, MAX_LONG_SIDE / Math.max(w, h))
    return [Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale))]
}

export async function blurOnly(input: Buffer): Promise<Buffer> {
    // Any libvips failure — bad header OR a corrupt/truncated body that fails mid-decode — is permanent for
    // these bytes, so map it all to UndecodableImageError (422/skip). A 500 here would poison the partition.
    try {
        const description = await inspectImage(input)
        const [tw, th] = targetDims(description.width, description.height)
        return await sharpForImage(input).resize(tw, th, { fit: 'fill' }).blur(BLUR_SIGMA).png().toBuffer()
    } catch (e) {
        throw e instanceof PermanentImageError ? e : new UndecodableImageError(String(e))
    }
}
