import sharp from 'sharp'

import { type StageTimings, compose } from './scrub.ts'

function timings(): StageTimings {
    return {
        decodeMs: 0,
        nsfwMs: 0,
        faceMs: 0,
        textMs: 0,
        codesMs: 0,
        composeMs: 0,
        encodeMs: 0,
        totalMs: 0,
        blanked: false,
        uniform: false,
        faces: 0,
        textBoxes: 0,
        codes: 0,
        format: 'png',
        inputPixels: 0,
        inputBytes: 0,
        storedPixels: 0,
    }
}

describe('compose', () => {
    const W = 800
    const H = 600
    const box = { left: 201, top: 137, width: 197, height: 143 }

    /** Thin dark strokes on white inside the box, so the mean-colour fill comes out light and any
     *  dark pixel in the result is content that escaped it rather than the fill itself. */
    async function strokesOnWhite(): Promise<{
        data: Buffer
        W: number
        H: number
        format: string
        inputPixels: number
    }> {
        // Flush to every edge of the box on purpose: a resize kernel reaching outward from the box
        // boundary has to find content there, or the fixture cannot show the leak it exists to catch.
        const strokes = []
        for (let y = box.top; y < box.top + box.height; y += 24) {
            strokes.push(`<rect x="${box.left}" y="${y}" width="${box.width}" height="5" fill="#000000"/>`)
        }
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
            <rect width="${W}" height="${H}" fill="#ffffff"/>${strokes.join('')}</svg>`
        // flatten to 3 channels exactly as decodeSrc does: Src is declared 3-channel, and an SVG
        // renders with alpha, so skipping it hands compose a buffer it reads misaligned.
        const { data, info } = await sharp(Buffer.from(svg))
            .flatten({ background: '#fff' })
            .raw()
            .toBuffer({ resolveWithObject: true })
        expect(info.channels).toBe(3)
        return { data, W, H, format: 'png', inputPixels: W * H }
    }

    async function darkPixels(png: Buffer): Promise<number> {
        const { data, info } = await sharp(png).raw().toBuffer({ resolveWithObject: true })
        let dark = 0
        for (let i = 0; i < data.length; i += info.channels) {
            if (data[i] < 100) {
                dark++
            }
        }
        return dark
    }

    // Nothing else covers compose or the storage encode: no test reaches advancedScrub, since it
    // needs the ONNX models. This is the only place a fill that stops surviving the encode would be
    // caught, and the storage path resizes between the fill and the PNG.
    //
    // It does NOT pin the ordering of fill against resize, which is the subtler property: resizing
    // first leaves a rim of what the box covered, because the kernel reaches past the box edge while
    // the outward rounding covers only a pixel of rounding. That ordering is verified structurally
    // (encodeStored can only receive already-composited pixels) and empirically against a solid
    // block, where the residue reached full intensity one pixel out at a 0.957 downscale. Through
    // compose it is not separable from the fill itself, whose colour is the region's own mean.
    it.each([1, 0.957, 0.5, 0.25])('keeps a filled region covered at storage scale %s', async (fraction) => {
        const out = await compose(await strokesOnWhite(), W, H, [box], timings(), Math.round(W * H * fraction))

        expect(await darkPixels(out)).toBe(0)
    })
})
