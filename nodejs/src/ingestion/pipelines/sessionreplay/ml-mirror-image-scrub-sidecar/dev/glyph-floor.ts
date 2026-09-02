/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Where detection fails against where legibility fails, as a function of glyph height.
 *
 * Megapixels are the wrong variable: 16pt text is the same physical size whether the frame is 0.6 MP
 * or 20 MP, so what decides whether DBNet finds it is how many pixels the glyph occupies by the time
 * the model sees it. This sweeps that directly, holding the frame size constant and varying only the
 * rendered size, then reports two thresholds:
 *
 *   detection floor  – below this, DBNet stops returning a box over the text
 *   legibility floor – below this, OCR stops reading it
 *
 * The gap between them is the danger zone: text that is missed and still readable. Detection failing
 * BELOW legibility is the safe ordering; the reverse means small text leaks intact.
 *
 * OCR is a conservative stand-in for a human, and conservative in the unhelpful direction: tesseract
 * gives up before a person does, so a glyph it cannot read may still be readable, and the real
 * legibility floor sits at or below what this prints.
 */
import sharp from 'sharp'
import { createWorker } from 'tesseract.js'

import { detectTextDbnet, loadDbnet } from '../src/dbnet.ts'
import { limitsFromEnv, planScales } from '../src/scale-plan.ts'
import { decodeSrc } from '../src/src-image.ts'

const FRAME_W = 1280
const FRAME_H = 720
const PHRASE = 'Account 4242 4242 4242 4242'
const SIZES = [4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20, 24, 32]

/** Rows of the same phrase at one size, spread down the frame so a single miss is not luck. */
function frameAt(fontPx: number): Promise<Buffer> {
    const rows = []
    for (let i = 0; i < 6; i++) {
        rows.push(
            `<text x="40" y="${60 + i * Math.max(fontPx * 2, 40)}" font-family="Arial" font-size="${fontPx}" fill="#111827">${PHRASE}</text>`
        )
    }
    return sharp(
        Buffer.from(
            `<svg xmlns="http://www.w3.org/2000/svg" width="${FRAME_W}" height="${FRAME_H}">` +
                `<rect width="${FRAME_W}" height="${FRAME_H}" fill="#ffffff"/>${rows.join('')}</svg>`
        )
    )
        .png()
        .toBuffer()
}

async function main(): Promise<void> {
    const dbnet = await loadDbnet('models/dbnet_det.onnx')
    const tess = await createWorker('eng')
    // Measured against the rendered frame through the real pipeline, not from the detection budget
    // alone. decodeSrc applies SCRUB_MAX_PIXELS first, so a glyph passes through two reductions
    // before the model sees it; taking only the second overstated this column by about 10% and the
    // floors quoted from it are what DETECT_OVER_STORE is derived from.
    const limits = limitsFromEnv()
    const probePlan = planScales({ width: FRAME_W, height: FRAME_H }, limits)
    const atModel = probePlan.text.content.width / FRAME_W
    console.log(
        `frame ${FRAME_W}x${FRAME_H} -> decoded ${probePlan.frame.width}x${probePlan.frame.height} -> ` +
            `model ${probePlan.text.content.width}px wide; glyphs reach DBNet at ${atModel.toFixed(3)}x\n`
    )
    console.log(
        `  ${'font px'.padStart(8)}${'at model'.padStart(10)}${'boxes'.padStart(7)}${'OCR words'.padStart(11)}   verdict`
    )

    for (const fontPx of SIZES) {
        const png = await frameAt(fontPx)
        const src = await decodeSrc(png)
        const boxes = await detectTextDbnet(dbnet, src, planScales({ width: src.W, height: src.H }, limits).text)
        const { data } = await tess.recognize(png, {}, { blocks: true })
        const words = (data.blocks ?? []).flatMap((b: any) =>
            (b.paragraphs ?? []).flatMap((p: any) => (p.lines ?? []).flatMap((l: any) => l.words ?? []))
        ) as { text: string; confidence: number }[]
        const readable = words.filter((w) => w.confidence >= 60 && /[A-Za-z0-9]{2,}/.test(w.text ?? '')).length
        const found = boxes.length > 0
        const verdict = found
            ? readable > 0
                ? 'detected + readable'
                : 'detected, already illegible'
            : readable > 0
              ? 'MISSED BUT READABLE'
              : 'missed, illegible anyway'
        console.log(
            `  ${String(fontPx).padStart(8)}${(fontPx * atModel).toFixed(1).padStart(10)}${String(boxes.length).padStart(7)}${String(readable).padStart(11)}   ${verdict}`
        )
    }
    await tess.terminate()
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
