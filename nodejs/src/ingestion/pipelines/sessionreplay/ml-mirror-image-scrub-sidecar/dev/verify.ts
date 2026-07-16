/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Self-verifying test: a scrubbed image should contain no READABLE text. We scrub with PRODUCTION
 * settings, then run OCR (tesseract — an independent model doing recognition, not the DBNet detector
 * used in production) on both the original and the scrubbed output, and count confident multi-char
 * words. CPU doesn't matter here, so OCR is upscaled for maximum sensitivity.
 *
 * Why OCR and not "re-run the detector": the verifier must be independent of production, and it must
 * measure the thing that actually matters — can a human read the text. OCR generally reads degraded
 * text better than people, so "OCR can't read it" is a conservative proxy for "a labeler can't".
 *
 * Saves out/verify_<name>.png with any residual readable-word boxes drawn in red.
 *
 * Usage: tsx src/verify.ts [img ...]
 */
import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import sharp from 'sharp'
import { type Worker, createWorker } from 'tesseract.js'

import { advancedScrub, loadModels } from '../src/scrub.ts'

const OCR_CONF = 60 // min tesseract word confidence to count as "readable"
const OCR_UPSCALE = 2 // upscale before OCR for max sensitivity (CPU irrelevant for a test)

interface Word {
    text: string
    confidence: number
    bbox: { x0: number; y0: number; x1: number; y1: number }
}

/** Confident, multi-character alphanumeric words OCR can read from an image (upscaled for recall). */
async function readableWords(tess: Worker, img: Buffer, W: number, H: number): Promise<Word[]> {
    const big = await sharp(img)
        .resize(Math.round(W * OCR_UPSCALE), Math.round(H * OCR_UPSCALE), { fit: 'fill' })
        .png()
        .toBuffer()
    const { data } = await tess.recognize(big, {}, { blocks: true })
    const words = ((data as { words?: Word[] }).words ??
        (data.blocks ?? []).flatMap((b: any) =>
            (b.paragraphs ?? []).flatMap((p: any) => (p.lines ?? []).flatMap((l: any) => l.words ?? []))
        )) as Word[]
    return words.filter((w) => w.confidence >= OCR_CONF && /[A-Za-z0-9]{2,}/.test(w.text ?? ''))
}

async function main(): Promise<void> {
    const models = await loadModels()
    const tess = await createWorker('eng')
    const imgs = process.argv.slice(2)
    const files = imgs.length
        ? imgs
        : ['out/original_wikipedia.png', 'corpus/shot_desktop_1280x720_0.png', 'corpus/shot_mobile_375x812_0.png']

    let worst = 0
    for (const f of files) {
        const buf = await readFile(f)
        const meta = await sharp(buf).metadata()
        const W = meta.width!
        const H = meta.height!
        const origWords = await readableWords(tess, buf, W, H)
        const { out } = await advancedScrub(buf, models, 'dbnet')
        const residWords = await readableWords(tess, out, W, H)
        const leak = (100 * residWords.length) / Math.max(1, origWords.length)
        worst = Math.max(worst, leak)
        const flag = residWords.length === 0 ? 'PASS' : leak < 2 ? 'ok' : 'LEAK'
        console.log(
            `  ${flag.padEnd(4)} ${basename(f).padEnd(34)} readable(orig)=${String(origWords.length).padStart(4)}  readable(scrubbed)=${String(residWords.length).padStart(3)}  (${leak.toFixed(1)}%)`
        )
        if (residWords.length) {
            console.log(
                `        leaked: ${residWords
                    .slice(0, 8)
                    .map((w) => JSON.stringify(w.text))
                    .join(', ')}`
            )
        }
        const rects = residWords
            .map(
                (w) =>
                    `<rect x="${w.bbox.x0 / OCR_UPSCALE}" y="${w.bbox.y0 / OCR_UPSCALE}" width="${(w.bbox.x1 - w.bbox.x0) / OCR_UPSCALE}" height="${(w.bbox.y1 - w.bbox.y0) / OCR_UPSCALE}" fill="none" stroke="red" stroke-width="4"/>`
            )
            .join('')
        await sharp(out)
            .composite([{ input: Buffer.from(`<svg width="${W}" height="${H}">${rects}</svg>`), left: 0, top: 0 }])
            .toFile('out/verify_' + basename(f))
    }
    await tess.terminate()
    console.log(`\n  worst readable-text leak: ${worst.toFixed(1)}%  ${worst < 2 ? '-> PASS' : '-> needs tuning'}`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
