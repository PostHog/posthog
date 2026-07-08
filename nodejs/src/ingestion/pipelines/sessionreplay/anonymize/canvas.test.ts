import { runBlurJobs } from './blur'
import { scrubCanvasMutation } from './canvas'
import { BlurJob, ScrubContext } from './config'
import { defaultAllowLists } from './default-dict'

// A small patterned PNG (portable across libvips/libpng builds; solid colors blur to identical
// bytes, so we use a checkerboard the blur visibly changes).
const ONE_PX_PNG_BASE64 =
    'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAJUlEQVQokWN4plEBRyInbOAIlzjDINRAjCJk8cGoYRAG60iMBwA8H08Qor0ygQAAAABJRU5ErkJggg=='
// Must match BLANK_PNG_BASE64 in blur.ts (the fail-safe placeholder; never re-decoded).
const BLANK_PNG_BASE64 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

function makeCtx(): ScrubContext & { blurJobs: BlurJob[] } {
    return { allow: defaultAllowLists(), blurJobs: [] }
}

describe('anonymize/canvas', () => {
    it('redacts text drawn via fillText/strokeText (batched commands)', () => {
        const ctx = makeCtx()
        const data = {
            source: 9,
            id: 1,
            type: 0,
            commands: [
                { property: 'fillText', args: ['SecretCustomerName', 10, 20] },
                { property: 'strokeText', args: ['AnotherSecret', 0, 0] },
            ],
        }
        expect(scrubCanvasMutation(ctx, data)).toBe(true)
        expect(data.commands[0].args[0]).not.toContain('Secret')
        expect(data.commands[0].args[0]).toMatch(/^\*+$/)
        expect(data.commands[1].args[0]).toMatch(/^\*+$/)
        // Numeric coordinates are untouched.
        expect(data.commands[0].args[1]).toBe(10)
    })

    it('redacts text in the flattened single-command form', () => {
        const ctx = makeCtx()
        const data = { source: 9, id: 1, type: 0, property: 'fillText', args: ['HelloSecret', 1, 2] }
        expect(scrubCanvasMutation(ctx, data)).toBe(true)
        expect(data.args[0]).toMatch(/^\*+$/)
    })

    it('blanks a data:image arg synchronously and queues a blur job', () => {
        const ctx = makeCtx()
        const data = {
            source: 9,
            id: 1,
            type: 0,
            commands: [{ property: 'drawImage', args: [`data:image/png;base64,${ONE_PX_PNG_BASE64}`, 0, 0] }],
        }
        expect(scrubCanvasMutation(ctx, data)).toBe(true)
        // Raw image gone immediately (fail-safe), blur deferred.
        expect(data.commands[0].args[0]).not.toContain(ONE_PX_PNG_BASE64)
        expect(data.commands[0].args[0]).toMatch(/^data:image\/png;base64,/)
        expect(ctx.blurJobs).toHaveLength(1)
    })

    it('blanks an encoded image Blob snapshot and queues a blur job (ImageBitmap → Blob → ArrayBuffer)', () => {
        const ctx = makeCtx()
        const ab = { rr_type: 'ArrayBuffer', base64: ONE_PX_PNG_BASE64 }
        const data = {
            source: 9,
            id: 1,
            type: 0,
            commands: [
                {
                    property: 'drawImage',
                    args: [
                        { rr_type: 'ImageBitmap', args: [{ rr_type: 'Blob', type: 'image/png', data: [ab] }] },
                        0,
                        0,
                    ],
                },
            ],
        }
        expect(scrubCanvasMutation(ctx, data)).toBe(true)
        expect(ab.base64).toBe(BLANK_PNG_BASE64)
        expect(ctx.blurJobs).toHaveLength(1)
    })

    it('blanks a data:image src and URL-scrubs a remote src', () => {
        const ctx = makeCtx()
        const data = {
            source: 9,
            id: 1,
            type: 0,
            commands: [
                {
                    property: 'drawImage',
                    args: [{ rr_type: 'HTMLImageElement', src: `data:image/png;base64,${ONE_PX_PNG_BASE64}` }],
                },
                {
                    property: 'drawImage',
                    args: [{ rr_type: 'HTMLImageElement', src: 'https://cdn.example.com/users/SecretUser/a.png' }],
                },
            ],
        }
        expect(scrubCanvasMutation(ctx, data)).toBe(true)
        expect((data.commands[0].args[0] as any).src).toMatch(/^data:image\/png;base64,/)
        expect((data.commands[0].args[0] as any).src).not.toContain(ONE_PX_PNG_BASE64)
        expect((data.commands[1].args[0] as any).src).not.toContain('SecretUser')
        expect((data.commands[1].args[0] as any).src).toContain('https://cdn.example.com')
        expect(ctx.blurJobs).toHaveLength(1)
    })

    it('leaves non-image args (numbers, non-image ArrayBuffers) untouched', () => {
        const ctx = makeCtx()
        const buf = { rr_type: 'ArrayBuffer', base64: 'V0VCR0xCVUZGRVI=' } // not inside an image Blob
        const data = {
            source: 9,
            id: 1,
            type: 1,
            commands: [
                { property: 'setTransform', args: [1, 0, 0, 1, 0, 0] },
                { property: 'bufferData', args: [34962, buf, 35044] },
            ],
        }
        expect(scrubCanvasMutation(ctx, data)).toBe(false)
        expect(buf.base64).toBe('V0VCR0xCVUZGRVI=')
        expect(ctx.blurJobs).toHaveLength(0)
    })

    it('runs queued blur jobs end to end, swapping the blank for a real blurred image', async () => {
        const ctx = makeCtx()
        const ab = { rr_type: 'ArrayBuffer', base64: ONE_PX_PNG_BASE64 }
        const data = {
            source: 9,
            id: 1,
            type: 0,
            commands: [{ property: 'drawImage', args: [{ rr_type: 'Blob', type: 'image/png', data: [ab] }, 0, 0] }],
        }
        scrubCanvasMutation(ctx, data)
        await runBlurJobs(ctx.blurJobs)
        // After blurring: not the blank placeholder and not the original.
        expect(ab.base64).not.toBe(BLANK_PNG_BASE64)
        expect(ab.base64).not.toBe(ONE_PX_PNG_BASE64)
    })

    // Build a putImageData command holding a W×H RGBA buffer with a non-uniform pattern.
    const W = 32
    const H = 32
    function rawImageDataCommand(): { ab: { rr_type: string; base64: string }; data: Record<string, unknown> } {
        const rgba = Buffer.alloc(W * H * 4)
        for (let i = 0; i < W * H; i++) {
            rgba[i * 4] = (i * 7) & 255
            rgba[i * 4 + 1] = (i * 3) & 255
            rgba[i * 4 + 2] = 200
            rgba[i * 4 + 3] = 255
        }
        const ab = { rr_type: 'ArrayBuffer', base64: rgba.toString('base64') }
        const data = {
            source: 9,
            id: 1,
            type: 0,
            property: 'putImageData',
            args: [
                { rr_type: 'ImageData', args: [{ rr_type: 'Uint8ClampedArray', args: [ab, 0, W * H * 4] }, W, H] },
                0,
                0,
            ],
        }
        return { ab, data }
    }

    it('blanks raw ImageData pixels synchronously and queues a pixelate job', () => {
        const ctx = makeCtx()
        const { ab, data } = rawImageDataCommand()
        const original = ab.base64
        expect(scrubCanvasMutation(ctx, data)).toBe(true)
        const blanked = Buffer.from(ab.base64, 'base64')
        expect(blanked.length).toBe(W * H * 4)
        expect(blanked.every((b) => b === 0)).toBe(true) // raw pixels gone immediately
        expect(ab.base64).not.toBe(original)
        expect(ctx.blurJobs).toHaveLength(1)
    })

    it('runs the ImageData pixelate job: same byte length, restored content, not the original', async () => {
        const ctx = makeCtx()
        const { ab, data } = rawImageDataCommand()
        const original = ab.base64
        scrubCanvasMutation(ctx, data)
        await runBlurJobs(ctx.blurJobs)
        const out = Buffer.from(ab.base64, 'base64')
        expect(out.length).toBe(W * H * 4) // dimensions preserved for putImageData
        expect(out.every((b) => b === 0)).toBe(false) // pixelated content restored
        expect(ab.base64).not.toBe(original) // but not the original detail
    })
})
