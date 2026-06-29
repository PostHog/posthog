/**
 * Scrubs rrweb CanvasMutation events: redacts text drawn via fill/strokeText and
 * Gaussian-blurs drawn images and canvas snapshots.
 *
 * Canvas data is either batched (`{ commands: [{property, args, setter?}] }`) or a
 * single flattened command (`{ property, args, setter? }`). Each `args` entry is a
 * recursive `CanvasArg`: primitives, arrays, or serialized objects —
 *   { rr_type: 'ArrayBuffer', base64 }
 *   { rr_type: 'Blob', data: CanvasArg[], type? }   // encoded image snapshot
 *   { rr_type, src }                                // HTMLImageElement etc.
 *   { rr_type, args: CanvasArg[] }                  // ImageBitmap etc.
 *   { rr_type: 'ImageData', args: [pixels, w, h] }  // putImageData raw RGBA
 * Images are neutralized synchronously (fail-safe) and the real downsampled/blurred
 * result is swapped in by the deferred blur job on success.
 */
import { BLANK_IMAGE_DATA_URI, BLANK_PNG_BASE64, blurImageDataUri, isImageDataUri, pixelateRawRgba } from './blur'
import { ScrubContext, isObject } from './config'
import { scrubText } from './text'
import { scrubUrl } from './url'

// Canvas API calls whose leading string arguments are user-visible text.
const TEXT_COMMANDS = new Set(['fillText', 'strokeText'])

/** Scrub a CanvasMutation `data` object in place. Returns whether anything changed. */
export function scrubCanvasMutation(ctx: ScrubContext, data: Record<string, unknown>): boolean {
    let changed = false
    if (Array.isArray(data.commands)) {
        for (const cmd of data.commands) {
            if (isObject(cmd)) {
                changed = scrubCommand(ctx, cmd) || changed
            }
        }
    } else if (typeof data.property === 'string') {
        // Flattened single-command form: `data` itself is the command.
        changed = scrubCommand(ctx, data) || changed
    }
    return changed
}

function scrubCommand(ctx: ScrubContext, cmd: Record<string, unknown>): boolean {
    if (!Array.isArray(cmd.args)) {
        return false
    }
    const args = cmd.args
    let changed = false

    // Text drawn onto the canvas: fillText/strokeText take the text as leading string args.
    if (typeof cmd.property === 'string' && TEXT_COMMANDS.has(cmd.property)) {
        for (let i = 0; i < args.length; i++) {
            if (typeof args[i] === 'string') {
                const result = scrubText(ctx, args[i])
                if (result.changed) {
                    args[i] = result.value
                    changed = true
                }
            }
        }
    }

    // Images/snapshots can appear anywhere in the (recursive) arg tree.
    for (let i = 0; i < args.length; i++) {
        changed = blurCanvasArg(ctx, args, i) || changed
    }
    return changed
}

/** Recursively neutralize+blur image data inside a canvas arg, mutating in place. */
function blurCanvasArg(ctx: ScrubContext, container: any, key: string | number): boolean {
    const value = container[key]

    if (typeof value === 'string') {
        if (isImageDataUri(value)) {
            queueImageBlur(ctx, value, (blurred) => (container[key] = blurred))
            container[key] = BLANK_IMAGE_DATA_URI
            return true
        }
        return false
    }

    if (Array.isArray(value)) {
        let changed = false
        for (let i = 0; i < value.length; i++) {
            changed = blurCanvasArg(ctx, value, i) || changed
        }
        return changed
    }

    if (!isObject(value)) {
        return false
    }

    // Serialized image element: { rr_type, src }. Data-URI src is an embedded image; a
    // remote src is a URL that may itself carry PII.
    if (typeof value.src === 'string') {
        if (isImageDataUri(value.src)) {
            const original = value.src
            value.src = BLANK_IMAGE_DATA_URI
            queueImageBlur(ctx, original, (blurred) => (value.src = blurred))
            return true
        }
        const result = scrubUrl(ctx, value.src)
        if (result.changed) {
            value.src = result.value
            return true
        }
        return false
    }

    // Encoded image snapshot: { rr_type: 'Blob', type: 'image/...', data: [ {rr_type:'ArrayBuffer', base64} ] }.
    if (value.rr_type === 'Blob' && typeof value.type === 'string' && value.type.startsWith('image/')) {
        return blurBlobImage(ctx, value)
    }

    // Raw pixels: { rr_type: 'ImageData', args: [pixels, width, height] } (putImageData).
    if (value.rr_type === 'ImageData') {
        return blurImageData(ctx, value)
    }

    // Otherwise recurse into nested arg/data arrays (ImageBitmap → Blob, etc.).
    let changed = false
    if (Array.isArray(value.args)) {
        for (let i = 0; i < value.args.length; i++) {
            changed = blurCanvasArg(ctx, value.args, i) || changed
        }
    }
    if (Array.isArray(value.data)) {
        for (let i = 0; i < value.data.length; i++) {
            changed = blurCanvasArg(ctx, value.data, i) || changed
        }
    }
    return changed
}

/** Blur the encoded image bytes inside an image Blob, neutralizing them first (fail-safe). */
function blurBlobImage(ctx: ScrubContext, blob: Record<string, unknown>): boolean {
    const data = blob.data
    if (!Array.isArray(data)) {
        return false
    }
    const ab = data.find(
        (d): d is Record<string, unknown> => isObject(d) && d.rr_type === 'ArrayBuffer' && typeof d.base64 === 'string'
    )
    if (!ab) {
        return false
    }
    const mime = typeof blob.type === 'string' ? blob.type : 'image/png'
    const original = `data:${mime};base64,${ab.base64 as string}`
    // Fail-safe: drop the raw snapshot to a blank pixel now; the job swaps in the blur on success.
    ab.base64 = BLANK_PNG_BASE64
    blob.type = 'image/png'
    queueImageBlur(ctx, original, (blurred) => {
        const parts = splitDataUri(blurred)
        if (parts) {
            ab.base64 = parts.base64
            blob.type = parts.mime
        }
    })
    return true
}

function queueImageBlur(ctx: ScrubContext, dataUri: string, apply: (blurred: string) => void): void {
    ctx.blurJobs?.push(async () => {
        const blurred = await blurImageDataUri(dataUri)
        if (blurred !== null) {
            apply(blurred)
        }
    })
}

interface RawLoc {
    ab: Record<string, unknown>
    start: number
    length: number
}

/** Locate the RGBA ArrayBuffer behind an ImageData's pixel descriptor (direct or typed-array-wrapped). */
function findRawBuffer(desc: unknown): RawLoc | null {
    if (!isObject(desc)) {
        return null
    }
    if (desc.rr_type === 'ArrayBuffer' && typeof desc.base64 === 'string') {
        return { ab: desc, start: 0, length: Buffer.from(desc.base64, 'base64').length }
    }
    // Typed-array wrapper: { rr_type: 'Uint8ClampedArray', args: [ {ArrayBuffer}, byteOffset?, length? ] }.
    if (Array.isArray(desc.args) && isObject(desc.args[0]) && desc.args[0].rr_type === 'ArrayBuffer') {
        const ab = desc.args[0] as Record<string, unknown>
        if (typeof ab.base64 !== 'string') {
            return null
        }
        const full = Buffer.from(ab.base64, 'base64').length
        const start = typeof desc.args[1] === 'number' ? desc.args[1] : 0
        const length = typeof desc.args[2] === 'number' ? desc.args[2] : full - start
        return { ab, start, length }
    }
    return null
}

/** Pixelate raw ImageData pixels in place (fail-safe blanked now, downsampled-and-restored by the job). */
function blurImageData(ctx: ScrubContext, imageData: Record<string, unknown>): boolean {
    const args = imageData.args
    if (Array.isArray(args)) {
        const width = args[1]
        const height = args[2]
        const loc =
            typeof width === 'number' && typeof height === 'number' && width > 0 && height > 0
                ? findRawBuffer(args[0])
                : null
        if (loc && loc.length === width * height * 4) {
            const full = Buffer.from(loc.ab.base64 as string, 'base64')
            if (loc.start >= 0 && loc.start + loc.length <= full.length) {
                const rgba = full.subarray(loc.start, loc.start + loc.length).toString('base64')
                const blanked = Buffer.from(full)
                blanked.fill(0, loc.start, loc.start + loc.length)
                loc.ab.base64 = blanked.toString('base64')
                ctx.blurJobs?.push(async () => {
                    const out = await pixelateRawRgba(rgba, width, height)
                    if (out === null) {
                        return
                    }
                    const outBuf = Buffer.from(out, 'base64')
                    if (outBuf.length !== loc.length) {
                        return
                    }
                    const merged = Buffer.from(blanked)
                    outBuf.copy(merged, loc.start)
                    loc.ab.base64 = merged.toString('base64')
                })
                return true
            }
        }
    }
    // Unexpected shape — guarantee no raw-pixel leak by blanking every nested ArrayBuffer.
    return blankArrayBuffers(imageData)
}

/** Zero out every nested `{rr_type:'ArrayBuffer', base64}` (same byte length). Last-resort fail-safe. */
function blankArrayBuffers(node: unknown): boolean {
    if (Array.isArray(node)) {
        let changed = false
        for (const item of node) {
            changed = blankArrayBuffers(item) || changed
        }
        return changed
    }
    if (!isObject(node)) {
        return false
    }
    if (node.rr_type === 'ArrayBuffer' && typeof node.base64 === 'string') {
        node.base64 = Buffer.alloc(Buffer.from(node.base64, 'base64').length).toString('base64')
        return true
    }
    let changed = false
    for (const key of Object.keys(node)) {
        changed = blankArrayBuffers((node as Record<string, unknown>)[key]) || changed
    }
    return changed
}

function splitDataUri(uri: string): { mime: string; base64: string } | null {
    const comma = uri.indexOf(',')
    if (!uri.startsWith('data:') || comma === -1) {
        return null
    }
    const mime = uri.slice('data:'.length, comma).split(';')[0] || 'image/png'
    return { mime, base64: uri.slice(comma + 1) }
}
