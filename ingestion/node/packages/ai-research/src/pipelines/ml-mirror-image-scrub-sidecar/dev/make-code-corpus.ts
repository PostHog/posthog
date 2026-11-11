/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Screenshots with real machine-decodable codes composited in, for testing the code detector's
 * recall against its cost. The eval corpus has exactly one code in 113 images, which is enough to
 * notice a total outage and nothing else.
 *
 * Codes are written by zxing's own encoder, so what the detector is asked to find is what a reader
 * would actually decode. Sizes span the range a code appears at on screen, from a small inline
 * ticket barcode to a full-panel provisioning QR.
 *
 * Output: ./code-corpus/*.png
 */
import { readFileSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import sharp from 'sharp'
import { prepareZXingModule, writeBarcode } from 'zxing-wasm/writer'

const wasmFile = createRequire(`${process.cwd()}/`).resolve('zxing-wasm/writer/zxing_writer.wasm')
const wasmBytes = readFileSync(wasmFile)
prepareZXingModule({
    overrides: {
        wasmBinary: wasmBytes.buffer.slice(wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength),
    },
})

const OUT = new URL('../code-corpus/', import.meta.url).pathname

// The payloads a real replay would carry: a TOTP provisioning URI, a ticket, an account reference.
const PAYLOADS: [string, 'QRCode' | 'DataMatrix' | 'Aztec' | 'Code128' | 'PDF417'][] = [
    ['otpauth://totp/Acme:jane.doe@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Acme', 'QRCode'],
    ['https://acme.example.com/invoice/2026-0042?token=b7f3a91c', 'QRCode'],
    ['ACCT-0098761234', 'DataMatrix'],
    ['TICKET-A1B2C3-SEAT-14F', 'Aztec'],
    ['4242424242424242', 'Code128'],
]

/** Code side in pixels, as it would appear inside a 1920x1080-ish frame. */
const SIDES = [96, 160, 280]

async function main(): Promise<void> {
    await mkdir(OUT, { recursive: true })
    let n = 0
    for (const [payload, format] of PAYLOADS) {
        for (const side of SIDES) {
            const { svg } = await writeBarcode(payload, { format })
            const code = await sharp(Buffer.from(svg))
                .resize(side, side, { fit: 'inside', kernel: 'nearest' })
                .flatten({ background: '#fff' })
                .png()
                .toBuffer()
            const { width, height } = await sharp(code).metadata()
            // A plain page with the code placed off-centre, so detection is not helped by it being
            // the only thing present or by sitting at a predictable origin.
            const frame = await sharp({
                create: { width: 1920, height: 1080, channels: 3, background: '#f3f4f6' },
            })
                .composite([{ input: code, left: 420, top: 260 }])
                .png()
                .toBuffer()
            const file = `code_${format}_${side}px_${n++}.png`
            await writeFile(OUT + file, frame)
            console.log(`  ${file}  ${width}x${height} code in 1920x1080`)
        }
    }
    console.log(`code corpus: ${n} images in ${OUT}`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
