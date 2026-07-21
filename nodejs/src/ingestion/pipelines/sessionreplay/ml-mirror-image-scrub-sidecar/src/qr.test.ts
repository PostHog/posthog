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

const writerWasm = readFileSync(require.resolve('zxing-wasm/writer/zxing_writer.wasm'))
prepareZXingModule({
    overrides: {
        wasmBinary: writerWasm.buffer.slice(writerWasm.byteOffset, writerWasm.byteOffset + writerWasm.byteLength),
    },
})

describe('detectCodes', () => {
    it('returns an in-bounds padded box covering a QR composited at a known location', async () => {
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

        const boxes = await detectCodes({ data, W: info.width, H: info.height })

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
    })
})
