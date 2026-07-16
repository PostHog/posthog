/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Test suite over many real images. Two independent checks, both end-to-end through advancedScrub:
 *
 *  TEXT: OCR (tesseract, a different model than the production DBNet detector) reads the scrubbed
 *        image and counts confident multi-character words; near-zero means the text is gone.
 *
 *  FACE: locate faces in the ORIGINAL with YuNet, scrub, then re-detect at high sensitivity on the
 *        output; a face still sitting (by IoU) where one was is a leak. A solid-filled face is no
 *        longer detectable, so this measures that redaction actually landed on the face.
 *
 * Gates on session replay's representative domain (rendered-UI text + faces) and reports on the
 * harder scanned-document set. Committed fixtures (e.g. the Wikipedia page) run in both checks.
 *
 *   npm run test   (exits non-zero on a gated text leak or an un-redacted face)
 */
import { existsSync } from 'node:fs'
import { readFile, readdir } from 'node:fs/promises'
import { basename, join } from 'node:path'
import sharp from 'sharp'
import { type Worker, createWorker } from 'tesseract.js'

import { type Models, advancedScrub, loadModels } from '../src/scrub.ts'
import { decodeSrc } from '../src/src-image.ts'
import { detectFacesYunet } from '../src/yunet.ts'

const ROOT = new URL('..', import.meta.url).pathname
const OCR_CONF = 60
const OCR_UPSCALE = 2
const OCR_MAX_LONG = 2200 // cap OCR input long side so retina fixtures don't become 30+ megapixels
const TEXT_LEAK_MAX_PCT = 2 // allow a little sub-lexical OCR noise

async function listImages(dir: string): Promise<string[]> {
    const p = join(ROOT, dir)
    if (!existsSync(p)) {
        return []
    }
    return (await readdir(p)).filter((f) => /\.(png|jpg|jpeg)$/i.test(f)).map((f) => join(p, f))
}

interface Word {
    text: string
    confidence: number
}

async function readableWords(tess: Worker, img: Buffer, W: number, H: number): Promise<number> {
    // Upscale small images for OCR sensitivity, but cap the long side so a retina screenshot
    // doesn't balloon to tens of megapixels (slow, and it's already high-res).
    const scale = Math.max(1, Math.min(OCR_UPSCALE, OCR_MAX_LONG / Math.max(W, H)))
    const big = await sharp(img)
        .resize(Math.round(W * scale), Math.round(H * scale), { fit: 'fill' })
        .png()
        .toBuffer()
    const { data } = await tess.recognize(big, {}, { blocks: true })
    const words = ((data as { words?: Word[] }).words ??
        (data.blocks ?? []).flatMap((b: any) =>
            (b.paragraphs ?? []).flatMap((p: any) => (p.lines ?? []).flatMap((l: any) => l.words ?? []))
        )) as Word[]
    return words.filter((w) => w.confidence >= OCR_CONF && /[A-Za-z0-9]{2,}/.test(w.text ?? '')).length
}

interface Box {
    left: number
    top: number
    width: number
    height: number
}
/** Intersection-over-union — used so a stray corner detection that merely touches a large face box
 *  doesn't count as "the face is still there". A real lingering face sits on top of the old one. */
function iou(a: Box, b: Box): number {
    const x1 = Math.max(a.left, b.left)
    const y1 = Math.max(a.top, b.top)
    const x2 = Math.min(a.left + a.width, b.left + b.width)
    const y2 = Math.min(a.top + a.height, b.top + b.height)
    const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
    return inter === 0 ? 0 : inter / (a.width * a.height + b.width * b.height - inter)
}
const SENSITIVE_FACE = 0.6 // re-detect threshold on the scrubbed image (below 0.7 prod, above noisy 0.4)
const LEAK_IOU = 0.2

async function testText(
    models: Models,
    tess: Worker,
    files: string[],
    label: string,
    gate: boolean
): Promise<{ pass: boolean }> {
    let worst = 0
    let fails = 0
    for (const f of files) {
        const buf = await readFile(f)
        const { width: W, height: H } = await sharp(buf).metadata()
        const orig = await readableWords(tess, buf, W!, H!)
        const { out } = await advancedScrub(buf, models, 'dbnet')
        const resid = await readableWords(tess, out, W!, H!)
        const leak = (100 * resid) / Math.max(1, orig)
        worst = Math.max(worst, leak)
        const ok = leak <= TEXT_LEAK_MAX_PCT
        if (!ok) {
            fails++
        }
        console.log(
            `  ${ok ? 'PASS' : 'leak'} text ${basename(f).padEnd(36)} orig=${String(orig).padStart(4)} scrubbed=${String(resid).padStart(3)} (${leak.toFixed(1)}%)`
        )
    }
    const verdict = gate ? (fails === 0 ? 'PASS' : 'FAIL') : 'report'
    console.log(
        `  ${label}: ${files.length - fails}/${files.length} clean, worst leak ${worst.toFixed(1)}% [${verdict}]\n`
    )
    return { pass: !gate || fails === 0 }
}

async function testFaces(models: Models, files: string[]): Promise<{ pass: boolean }> {
    let totalFaces = 0
    let redacted = 0
    let imgFails = 0
    for (const f of files) {
        const buf = await readFile(f)
        const { width: W, height: H } = await sharp(buf).metadata()
        const faces = await detectFacesYunet(models.yunet, await decodeSrc(buf), W!, H!)
        if (faces.length === 0) {
            continue
        }
        const { out } = await advancedScrub(buf, models, 'dbnet')
        // Re-detect at high sensitivity on the scrubbed output; a face that's still detectable where
        // one was is a leak. (A successfully solid-filled face is no longer detectable.)
        const resid = await detectFacesYunet(models.yunet, await decodeSrc(out), W!, H!, { scoreMin: SENSITIVE_FACE })
        const leaked = faces.filter((fb) => resid.some((rb) => iou(fb, rb) > LEAK_IOU))
        const imgRedacted = faces.length - leaked.length
        totalFaces += faces.length
        redacted += imgRedacted
        const ok = leaked.length === 0
        if (!ok) {
            imgFails++
        }
        console.log(
            `  ${ok ? 'PASS' : 'LEAK'} face ${basename(f).padEnd(36)} faces=${String(faces.length).padStart(3)} still-detectable=${String(leaked.length).padStart(3)}`
        )
    }
    const pct = totalFaces ? (100 * redacted) / totalFaces : 100
    console.log(
        `  FACE: ${redacted}/${totalFaces} faces redacted (${pct.toFixed(1)}%), ${imgFails} image(s) with a leak\n`
    )
    return { pass: imgFails === 0 }
}

async function main(): Promise<void> {
    const models = await loadModels()
    const tess = await createWorker('eng')

    // GATE on session replay's representative domain: crisp rendered-UI text + faces.
    // REPORT on the harder scanned-document set (faint fax/scan print is out of domain; the user's
    // bar is best-effort, "not catastrophic if a little gets through").
    // Committed challenge fixtures (e.g. a full retina Wikipedia page: dense text + a face + a
    // heraldic crest + a flag) exercise text and face redaction together, so they go in both lists.
    const fixtures = await listImages('fixtures')
    const uiText = [...(await listImages('corpus')), ...fixtures]
    const docText = await listImages('test-data/text')
    const faceFiles = [...(await listImages('test-data/faces')), ...fixtures]
    console.log(`UI text: ${uiText.length}   document text: ${docText.length}   faces: ${faceFiles.length}\n`)

    const ui = uiText.length ? await testText(models, tess, uiText, 'UI TEXT (gated)', true) : { pass: true }
    const docs = docText.length
        ? await testText(models, tess, docText, 'DOCUMENT TEXT (report)', false)
        : { pass: true }
    const fc = faceFiles.length ? await testFaces(models, faceFiles) : { pass: true }

    await tess.terminate()
    void docs
    const pass = ui.pass && fc.pass
    console.log(pass ? '=== PASS (gated checks) ===' : '=== FAILURES ===')
    if (!pass) {
        process.exit(1)
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
