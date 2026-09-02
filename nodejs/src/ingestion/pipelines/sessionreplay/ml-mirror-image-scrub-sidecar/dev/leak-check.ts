/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * OCR leak on a named set of images, for sweeping detector settings against the cases that fail.
 * Same measurement as scrub-eval's text check, over an argument list instead of the whole corpus, so
 * a threshold sweep costs seconds per setting rather than minutes.
 *
 *   PROB_T=0.2 DILATE_X=12 tsx dev/leak-check.ts corpus/shot_desktop_3840x2160_dpr1_*.png
 *
 * OCR reads the ORIGINAL at its own size and the scrubbed output rescaled to match, so settings that
 * shrink the output are not credited for text that merely became too small to read.
 */
import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import sharp from 'sharp'
import { type Worker, createWorker } from 'tesseract.js'

import { advancedScrub, loadModels } from '../src/scrub.ts'

const OCR_CONF = 60
const OCR_MAX_LONG = 2200

async function readableWords(tess: Worker, img: Buffer, W: number, H: number): Promise<number> {
    const scale = Math.max(1, Math.min(2, OCR_MAX_LONG / Math.max(W, H)))
    const big = await sharp(img)
        .resize(Math.round(W * scale), Math.round(H * scale), { fit: 'fill' })
        .png()
        .toBuffer()
    const { data } = await tess.recognize(big, {}, { blocks: true })
    const words = (data.blocks ?? []).flatMap((b: any) =>
        (b.paragraphs ?? []).flatMap((p: any) => (p.lines ?? []).flatMap((l: any) => l.words ?? []))
    ) as { text: string; confidence: number }[]
    return words.filter((w) => w.confidence >= OCR_CONF && /[A-Za-z0-9]{2,}/.test(w.text ?? '')).length
}

const files = process.argv.slice(2)
const models = await loadModels()
const tess = await createWorker('eng')
let worst = 0
let boxes = 0
let ms = 0
for (const f of files) {
    const buf = await readFile(f)
    const { width: W, height: H } = await sharp(buf).metadata()
    const orig = await readableWords(tess, buf, W!, H!)
    const { out, t } = await advancedScrub(buf, models, 'dbnet')
    const resid = await readableWords(tess, out, W!, H!)
    const leak = (100 * resid) / Math.max(1, orig)
    worst = Math.max(worst, leak)
    boxes += t.textBoxes
    ms += t.totalMs
    console.error(`  ${basename(f).padEnd(40)} ${orig} -> ${resid} (${leak.toFixed(1)}%) boxes=${t.textBoxes}`)
}
await tess.terminate()
console.log(
    JSON.stringify({
        label: process.env.SWEEP_LABEL ?? '',
        worstLeakPct: Number(worst.toFixed(1)),
        boxes,
        meanMs: Number((ms / files.length).toFixed(0)),
    })
)
