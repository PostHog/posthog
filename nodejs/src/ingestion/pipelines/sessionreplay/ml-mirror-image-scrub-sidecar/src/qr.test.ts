/**
 * detectCodes failing open (zero boxes, no error) would ship un-redacted codes, so this pins the
 * whole chain — wasm loading from node_modules, RGB->RGBA expansion, corner->padded-box mapping —
 * against a QR composited at a known location. Runs without the ONNX models, so it's the one
 * detector CI can exercise.
 */
import { readFileSync } from 'node:fs'
import sharp from 'sharp'
import { prepareZXingModule, writeBarcode } from 'zxing-wasm/writer'

import { detectCodes } from './qr.ts'
import { type Dims, limitsFromEnv, planScales } from './scale-plan.ts'
import { type Src, decodeSrc, srcSharp } from './src-image.ts'

const writerWasm = readFileSync(require.resolve('zxing-wasm/writer/zxing_writer.wasm'))
prepareZXingModule({
    overrides: {
        wasmBinary: writerWasm.buffer.slice(writerWasm.byteOffset, writerWasm.byteOffset + writerWasm.byteLength),
    },
})

/** What dev/code-bench.ts counts as a leak: zxing decodes the stored image as it is, or upscaled the way an attacker would. */
async function decodableFromStoredImage(src: Src, stored: Dims): Promise<boolean> {
    const art = await srcSharp(src).resize(stored.width, stored.height, { fit: 'fill' }).raw().toBuffer()
    for (const factor of [1, 2, 3]) {
        const [W, H] = [stored.width * factor, stored.height * factor]
        const data = await sharp(art, { raw: { width: stored.width, height: stored.height, channels: 3 } })
            .resize(W, H, { kernel: 'cubic' })
            .raw()
            .toBuffer()
        if ((await detectCodes({ data, W, H, format: 'raw', inputPixels: W * H })).length > 0) {
            return true
        }
    }
    return false
}

describe('detectCodes', () => {
    it.each([1, 0.75])(
        'returns an in-bounds padded box covering a QR at a known location, read at %s of the frame',
        async (scale) => {
            const qr = await writeBarcode('otpauth://totp/test?secret=JBSWY3DPEHPK3PXP', {
                format: 'QRCode',
                scale: 4,
            })
            const qrPng = Buffer.from(await qr.image!.arrayBuffer())
            const { width: qrW, height: qrH } = await sharp(qrPng).metadata()
            const [frameW, frameH, qrLeft, qrTop] = [800, 600, 500, 300]

            const { data, info } = await sharp({
                create: { width: frameW, height: frameH, channels: 3, background: '#fff' },
            })
                .composite([{ input: qrPng, left: qrLeft, top: qrTop }])
                .removeAlpha()
                .raw()
                .toBuffer({ resolveWithObject: true })

            const boxes = await detectCodes(
                { data, W: info.width, H: info.height, format: 'raw', inputPixels: info.width * info.height },
                scale
            )

            expect(boxes).toHaveLength(1)
            const b = boxes[0]
            expect(b.left).toBeGreaterThanOrEqual(0)
            expect(b.top).toBeGreaterThanOrEqual(0)
            expect(b.left + b.width).toBeLessThanOrEqual(frameW)
            expect(b.top + b.height).toBeLessThanOrEqual(frameH)
            // the padded box must fully cover the QR itself
            expect(b.left).toBeLessThanOrEqual(qrLeft)
            expect(b.top).toBeLessThanOrEqual(qrTop)
            expect(b.left + b.width).toBeGreaterThanOrEqual(qrLeft + qrW!)
            expect(b.top + b.height).toBeGreaterThanOrEqual(qrTop + qrH!)
        }
    )

    it('covers an Aztec code the stored image keeps decodable, read at the planned scale of a 1080p frame', async () => {
        const source = { width: 1920, height: 1080 }
        const plan = planScales(source, limitsFromEnv())
        // Aztec sets CODE_FLOOR, and at this size the stored image of a 1080p capture still decodes it.
        const [side, left, top] = [360, 1100, 380]
        const code = await writeBarcode('TICKET-A1B2C3-SEAT-14F', { format: 'Aztec', scale: 1 })
        const codePng = await sharp(Buffer.from(await code.image!.arrayBuffer()))
            .resize(side, side, { kernel: 'nearest' })
            .png()
            .toBuffer()
        const png = await sharp({
            create: { width: source.width, height: source.height, channels: 3, background: '#f3f4f6' },
        })
            .composite([{ input: codePng, left, top }])
            .png()
            .toBuffer()
        const src = await decodeSrc(png, plan.frame)

        expect(await decodableFromStoredImage(src, plan.stored)).toBe(true)

        const boxes = await detectCodes(src, plan.code.scale)
        const [fx, fy] = [src.W / source.width, src.H / source.height]
        const covered = boxes.some(
            (b) =>
                b.left <= left * fx &&
                b.top <= top * fy &&
                b.left + b.width >= (left + side) * fx &&
                b.top + b.height >= (top + side) * fy
        )
        expect(covered).toBe(true)
    })
})
