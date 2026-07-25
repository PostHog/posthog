/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Detection floors for faces and codes, against the floor at which each still carries information in
 * the stored artifact. The text version of this lives in glyph-floor.ts; the same question has to be
 * asked separately for each detector, because their inputs are sized on different rules: DBNet scales
 * with the frame, YuNet letterboxes into a fixed 640 square, and zxing works on the frame directly.
 *
 * For each subject size it reports two things:
 *   detected   – the production detector finds it at the detection resolution
 *   survives   – the same subject is still machine-recoverable from the downscaled artifact
 *
 * `survives` is the attacker's side of the trade. For codes it is exact: zxing either decodes the
 * stored image or it does not, and a code it cannot decode carries nothing. For faces it is a proxy:
 * a face YuNet can still find in the artifact is one a re-identification attempt has something to
 * work with, which is stricter than a human recognising it and so errs the safe way.
 *
 * Any row that is `survives` but not `detected` is a leak: present in what we keep, missed by what
 * redacts it.
 */
import { readFileSync } from 'node:fs'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import sharp from 'sharp'
import { prepareZXingModule, writeBarcode } from 'zxing-wasm/writer'

import { detectCodes } from '../src/qr.ts'
import { decodeSrc } from '../src/src-image.ts'
import { detectFacesYunet, loadYunet } from '../src/yunet.ts'

const wasmFile = createRequire(`${process.cwd()}/`).resolve('zxing-wasm/writer/zxing_writer.wasm')
const wasmBytes = readFileSync(wasmFile)
prepareZXingModule({
    overrides: {
        wasmBinary: wasmBytes.buffer.slice(wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength),
    },
})

const FRAME_W = 1920
const FRAME_H = 1080
/** The proposed shape: detect at 9x the output area, store at 0.1 MP. */
const DETECT_PX = 900_000
const STORE_PX = 100_000

async function place(subject: Buffer, sidePx: number): Promise<Buffer> {
    const scaled = await sharp(subject).resize(sidePx, sidePx, { fit: 'inside' }).toBuffer()
    return sharp({ create: { width: FRAME_W, height: FRAME_H, channels: 3, background: '#f3f4f6' } })
        .composite([{ input: scaled, left: 420, top: 260 }])
        .png()
        .toBuffer()
}

/** The frame as the detectors see it, and as the artifact keeps it. */
async function atScale(frame: Buffer, targetPx: number): Promise<Buffer> {
    const scale = Math.sqrt(targetPx / (FRAME_W * FRAME_H))
    return sharp(frame)
        .resize(Math.round(FRAME_W * scale), Math.round(FRAME_H * scale))
        .png()
        .toBuffer()
}

async function faceFloors(): Promise<void> {
    const yunet = await loadYunet('models/yunet.onnx')
    const dir = 'test-data/faces'
    const files = (await readdir(dir)).filter((f) => /\.(png|jpg|jpeg)$/i.test(f)).slice(0, 6)
    console.log('\n  FACES — subject placed at N px in a 1920x1080 frame\n')
    console.log(
        `  ${'face px'.padStart(8)}${'in artifact'.padStart(13)}${'detected'.padStart(10)}${'survives'.padStart(10)}   verdict`
    )
    for (const sidePx of [24, 32, 48, 64, 96, 128, 192]) {
        let detected = 0
        let survives = 0
        for (const f of files) {
            const frame = await place(await readFile(join(dir, f)), sidePx)
            const det = await decodeSrc(await atScale(frame, DETECT_PX))
            const art = await decodeSrc(await atScale(frame, STORE_PX))
            if ((await detectFacesYunet(yunet, det, det.W, det.H)).length > 0) {
                detected++
            }
            if ((await detectFacesYunet(yunet, art, art.W, art.H, { scoreMin: 0.6 })).length > 0) {
                survives++
            }
        }
        const inArtifact = sidePx * Math.sqrt(STORE_PX / (FRAME_W * FRAME_H))
        const leak = survives > detected
        console.log(
            `  ${String(sidePx).padStart(8)}${inArtifact.toFixed(1).padStart(13)}${`${detected}/${files.length}`.padStart(10)}${`${survives}/${files.length}`.padStart(10)}   ${leak ? 'LEAK: survives but missed' : survives === 0 ? 'gone from the artifact' : 'detected'}`
        )
    }
}

async function codeFloors(): Promise<void> {
    console.log('\n  CODES — QR placed at N px in a 1920x1080 frame\n')
    console.log(
        `  ${'code px'.padStart(8)}${'in artifact'.padStart(13)}${'detected'.padStart(10)}${'decodable'.padStart(11)}   verdict`
    )
    const { svg } = await writeBarcode('otpauth://totp/Acme:jane@example.com?secret=JBSWY3DPEHPK3PXP', {
        format: 'QRCode',
    })
    const code = await sharp(Buffer.from(svg)).png().toBuffer()
    for (const sidePx of [48, 64, 96, 128, 192, 280]) {
        const frame = await place(code, sidePx)
        const det = await decodeSrc(await atScale(frame, DETECT_PX))
        const art = await decodeSrc(await atScale(frame, STORE_PX))
        const detected = (await detectCodes(det)).length > 0
        const decodable = (await detectCodes(art)).length > 0
        const inArtifact = sidePx * Math.sqrt(STORE_PX / (FRAME_W * FRAME_H))
        console.log(
            `  ${String(sidePx).padStart(8)}${inArtifact.toFixed(1).padStart(13)}${(detected ? 'yes' : 'no').padStart(10)}${(decodable ? 'yes' : 'no').padStart(11)}   ${decodable && !detected ? 'LEAK: decodable but missed' : decodable ? 'detected' : 'gone from the artifact'}`
        )
    }
}

async function main(): Promise<void> {
    console.log(`  detection at ${DETECT_PX / 1e6} MP, artifact at ${STORE_PX / 1e6} MP`)
    await faceFloors()
    await codeFloors()
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
