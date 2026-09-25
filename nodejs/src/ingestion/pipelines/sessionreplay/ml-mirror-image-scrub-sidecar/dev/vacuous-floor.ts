/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Evidence for the `vacuousDetectors` bounds in src/floors.ts: what each detector finds on an image
 * that is small as a whole, and what survives in the raw stored artifact of that image.
 *
 * dev/floors.ts sweeps a subject placed in a large frame. This sweep shrinks the whole image, which
 * is the icon and thumbnail case the bounds exist for. For each image size it reports:
 *   on image    – the production detector finds the subject on the image itself
 *   on stored   – the same detector finds it on the raw artifact, at the size the plan stores it
 *   pipeline    – whether advancedScrub skipped the detector, and how many fills it drew
 *
 * A bound is safe while every image size it skips has zero under `on stored`. The face column also
 * reports YuNet at a score threshold of 0.3, which fires on blobs a few px wide, so read the default
 * threshold column as the finding and the 0.3 column as the upper limit of what a re-run could claim.
 *
 *   npm run floors:vacuous
 */
import { readFileSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import sharp from 'sharp'
import { prepareZXingModule, writeBarcode } from 'zxing-wasm/writer'

import { detectCodes } from '../src/qr.ts'
import { limitsFromEnv, planScales } from '../src/scale-plan.ts'
import { advancedScrub, disposeModels, loadModels } from '../src/scrub.ts'
import { decodeSrc, srcSharp } from '../src/src-image.ts'
import { detectFacesYunet } from '../src/yunet.ts'

sharp.concurrency(1)
const wasm = readFileSync(createRequire(`${process.cwd()}/`).resolve('zxing-wasm/writer/zxing_writer.wasm'))
prepareZXingModule({ overrides: { wasmBinary: wasm.buffer.slice(wasm.byteOffset, wasm.byteOffset + wasm.byteLength) } })

const FIXTURE = new URL('../fixtures/wikipedia_pm_uk.png', import.meta.url).pathname
const SIDES = [12, 16, 20, 21, 24, 32, 48, 64, 83, 96, 128, 160, 200, 250, 300]

const m = await loadModels()
const limits = limitsFromEnv()

/** The artifact with no redaction: the image at the size the plan stores it. */
async function rawStored(buf: Buffer): Promise<{ png: Buffer; width: number; height: number }> {
    const meta = await sharp(buf).metadata()
    const { stored } = planScales({ width: meta.width ?? 0, height: meta.height ?? 0 }, limits)
    const png = await sharp(buf).resize(stored.width, stored.height, { fit: 'fill' }).png().toBuffer()
    return { png, ...stored }
}

console.log('== face: the fixture face with a margin of one face each side, shrunk so the image side is N px')
const fixture = await readFile(FIXTURE)
const full = await decodeSrc(fixture)
const [face] = await detectFacesYunet(m.yunet, full, full.W, full.H)
const centreX = face.left + face.width / 2
const centreY = face.top + face.height / 2
const half = Math.max(face.width, face.height) * 1.5
const faceCrop = await srcSharp(full)
    .extract({
        left: Math.max(0, Math.round(centreX - half)),
        top: Math.max(0, Math.round(centreY - half)),
        width: Math.round(2 * half),
        height: Math.round(2 * half),
    })
    .png()
    .toBuffer()
for (const side of SIDES) {
    const buf = await sharp(faceCrop).resize(side, side, { fit: 'inside' }).png().toBuffer()
    const src = await decodeSrc(buf)
    const onImage = (await detectFacesYunet(m.yunet, src, src.W, src.H)).length
    const stored = await rawStored(buf)
    const storedSrc = await decodeSrc(stored.png)
    const onStored = (await detectFacesYunet(m.yunet, storedSrc, storedSrc.W, storedSrc.H)).length
    const onStoredLoose = (await detectFacesYunet(m.yunet, storedSrc, storedSrc.W, storedSrc.H, { scoreMin: 0.3 }))
        .length
    const { t } = await advancedScrub(buf, m)
    console.log(
        `image ${src.W}x${src.H}: on image=${onImage} | stored ${stored.width}x${stored.height}: on stored=${onStored} (score 0.3: ${onStoredLoose}) | pipeline: skipped=${t.faceVacuous} fills=${t.faces}`
    )
}

console.log('== code: a QR code with quiet zones, rendered so the image side is N px')
const qr = await writeBarcode('https://example.com/ticket/4711', { format: 'QRCode', withQuietZones: true })
for (const side of SIDES) {
    const buf = await sharp(Buffer.from(qr.svg)).resize(side, side, { fit: 'fill' }).png().toBuffer()
    const src = await decodeSrc(buf)
    const onImage = (await detectCodes(src)).length
    const stored = await rawStored(buf)
    const onStored = (await detectCodes(await decodeSrc(stored.png))).length
    const { t } = await advancedScrub(buf, m)
    console.log(
        `image ${src.W}x${src.H}: on image=${onImage} | stored ${stored.width}x${stored.height}: on stored=${onStored} | pipeline: skipped=${t.codesVacuous} fills=${t.codes}`
    )
}

console.log('== text: "Hello 4711" rendered in an image N px tall; text detection has no bound')
for (const [width, height, font] of [
    [200, 63, 40],
    [120, 40, 26],
    [80, 24, 16],
    [60, 16, 11],
    [40, 12, 8],
]) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="white"/><text x="4" y="${Math.round(height * 0.75)}" font-family="sans-serif" font-size="${font}" fill="black">Hello 4711</text></svg>`
    const { t } = await advancedScrub(await sharp(Buffer.from(svg)).png().toBuffer(), m)
    console.log(
        `image ${width}x${height} font ${font}px: text boxes=${t.textBoxes} skipped face=${t.faceVacuous} codes=${t.codesVacuous}`
    )
}
await disposeModels(m)
