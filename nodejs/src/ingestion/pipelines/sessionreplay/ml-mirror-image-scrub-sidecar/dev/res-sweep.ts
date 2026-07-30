/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * One resolution setting, measured over every local image: what the detectors find and what it cost.
 *
 * limitsFromEnv().framePixels and DET_FACTOR are read once at module load, so a sweep runs this process per
 * setting rather than looping inside one. Prints a JSON line per run for diffing across them.
 *
 *   SCRUB_OUT_MAX_PIXELS=25000 tsx dev/res-sweep.ts smaller-artifact
 *
 * Box counts are the direct read on detection recall. The eval's OCR leak percentage is end-to-end
 * but confounded here: a smaller output makes residual text harder for tesseract to read whether or
 * not it was redacted, which flatters exactly the settings under test.
 */
import { existsSync } from 'node:fs'
import { readFile, readdir } from 'node:fs/promises'
import { basename, join } from 'node:path'
import sharp from 'sharp'

import { limitsFromEnv } from '../src/scale-plan.ts'
import { advancedScrub, loadModels } from '../src/scrub.ts'

const ROOT = new URL('..', import.meta.url).pathname

async function listImages(dir: string): Promise<string[]> {
    const p = join(ROOT, dir)
    if (!existsSync(p)) {
        return []
    }
    return (await readdir(p)).filter((f) => /\.(png|jpg|jpeg)$/i.test(f)).map((f) => join(p, f))
}

async function main(): Promise<void> {
    const label = process.argv[2] ?? 'run'
    const models = await loadModels()
    const files = [
        ...(await listImages(process.env.SWEEP_DIR ?? 'corpus')),
        ...(process.env.SWEEP_DIR ? [] : await listImages('fixtures')),
        ...(process.env.SWEEP_DIR ? [] : await listImages('test-data/text')),
        ...(process.env.SWEEP_DIR ? [] : await listImages('test-data/faces')),
    ]

    // The first scrub of a process pays one-off native init, so spend it before timing anything.
    if (files.length) {
        await advancedScrub(await readFile(files[0]), models, 'dbnet')
    }

    const rows: Record<string, number | string>[] = []
    for (const f of files) {
        const buf = await readFile(f)
        const meta = await sharp(buf).metadata()
        const { out, t } = await advancedScrub(buf, models, 'dbnet')
        const outMeta = await sharp(out).metadata()
        rows.push({
            file: basename(f),
            srcMp: (meta.width! * meta.height!) / 1e6,
            outMp: (outMeta.width! * outMeta.height!) / 1e6,
            textBoxes: t.textBoxes,
            faces: t.faces,
            codes: t.codes,
            outBytes: out.length,
            totalMs: t.totalMs,
            textMs: t.textMs,
            faceMs: t.faceMs,
            nsfwMs: t.nsfwMs,
            codesMs: t.codesMs,
            composeMs: t.composeMs,
            encodeMs: t.encodeMs,
            decodeMs: t.decodeMs,
        })
        const srcMp = (meta.width! * meta.height!) / 1e6
        const outMp = (outMeta.width! * outMeta.height!) / 1e6
        console.error(
            `  ${basename(f).padEnd(44)} ${srcMp.toFixed(2)}MP -> ${outMp.toFixed(2)}MP ` +
                `text=${t.textBoxes} faces=${t.faces} codes=${t.codes} ${t.totalMs.toFixed(0)}ms`
        )
    }

    console.log(
        JSON.stringify({
            label,
            scrubMaxPixels: limitsFromEnv().framePixels,
            rows,
        })
    )
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
