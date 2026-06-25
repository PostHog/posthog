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
 * Images are neutralized to a blank pixel synchronously (fail-safe) and the real
 * blurred result is swapped in by the deferred blur job on success.
 */
import { BLANK_IMAGE_DATA_URI, BLANK_PNG_BASE64, isImageDataUri } from './blur'
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
    ctx.blurJobs?.push({ dataUri, apply })
}

function splitDataUri(uri: string): { mime: string; base64: string } | null {
    const comma = uri.indexOf(',')
    if (!uri.startsWith('data:') || comma === -1) {
        return null
    }
    const mime = uri.slice('data:'.length, comma).split(';')[0] || 'image/png'
    return { mime, base64: uri.slice(comma + 1) }
}
