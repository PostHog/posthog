/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Build a small, representative corpus of session-replay-ish images:
 *  - synthetic "screenshots" (text-heavy UI) at desktop + mobile sizes  -> exercises the text path
 *  - a few real photos with faces (fetched; falls back to synthetic if offline) -> exercises faces
 * Output: ./corpus/*.png  (+ manifest.json with byte sizes)
 */
import { mkdir, writeFile } from 'node:fs/promises'
import sharp from 'sharp'

const OUT = new URL('../corpus/', import.meta.url).pathname

function screenshotSvg(w: number, h: number, seed: number): Buffer {
    const rows: string[] = []
    const lines = [
        'Dashboard  Settings  Profile  Billing  Log out',
        'Total revenue $48,201.55   +12.4% MoM',
        'jane.doe@example.com   +1 (415) 555-0132',
        'Card ending 4242   Exp 08/27   CVC •••',
        'Order #A1B2C3   Ship to 1200 Market St, San Francisco CA 94103',
        'Invoice 2026-0042   Due 2026-07-15   Amount 1,299.00',
        'SSN 123-45-6789   DOB 1990-04-12   Acct 0098761234',
        'Search results for "quarterly forecast q3 2026"',
    ]
    let y = 40
    for (let i = 0; i < 18; i++) {
        const text = lines[(i + seed) % lines.length]
        rows.push(
            `<text x="32" y="${y}" font-family="Arial" font-size="${14 + ((i + seed) % 6)}" fill="#1f2937">${text}</text>`
        )
        y += Math.floor(h / 20)
    }
    return Buffer.from(
        `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">
           <rect width="${w}" height="${h}" fill="#ffffff"/>
           <rect width="${w}" height="56" fill="#111827"/>
           <text x="32" y="36" font-family="Arial" font-size="22" fill="#ffffff">Acme Analytics</text>
           ${rows.join('\n')}
         </svg>`
    )
}

async function fetchPhoto(url: string, w: number, h: number): Promise<Buffer | null> {
    try {
        const res = await fetch(url, { signal: AbortSignal.timeout(15000) })
        if (!res.ok) {
            return null
        }
        const buf = Buffer.from(await res.arrayBuffer())
        return await sharp(buf).resize(w, h, { fit: 'cover' }).png().toBuffer()
    } catch {
        return null
    }
}

async function main(): Promise<void> {
    await mkdir(OUT, { recursive: true })
    const manifest: { file: string; bytes: number; kind: string }[] = []

    const sizes: [number, number, string][] = [
        [1280, 720, 'desktop'],
        [1440, 900, 'desktop'],
        [375, 812, 'mobile'],
        [390, 844, 'mobile'],
    ]
    let i = 0
    for (const [w, h, kind] of sizes) {
        for (let k = 0; k < 3; k++) {
            const png = await sharp(screenshotSvg(w, h, i + k))
                .png()
                .toBuffer()
            const file = `shot_${kind}_${w}x${h}_${k}.png`
            await writeFile(OUT + file, png)
            manifest.push({ file, bytes: png.length, kind: `screenshot_${kind}` })
            i++
        }
    }

    // Real faces. thispersondoesnotexist serves a fresh synthetic face each hit (no real person, CC-ish).
    const faceUrls = [
        'https://thispersondoesnotexist.com/',
        'https://thispersondoesnotexist.com/',
        'https://thispersondoesnotexist.com/',
    ]
    let faceCount = 0
    for (let f = 0; f < faceUrls.length; f++) {
        const photo = await fetchPhoto(faceUrls[f], 512, 512)
        if (photo) {
            const file = `face_${f}.png`
            await writeFile(OUT + file, photo)
            manifest.push({ file, bytes: photo.length, kind: 'face_photo' })
            faceCount++
        }
    }
    if (faceCount === 0) {
        console.warn(
            '!! no face photos fetched (offline?). Face path will see 0 detections; numbers still valid for cost.'
        )
    }

    await writeFile(OUT + 'manifest.json', JSON.stringify(manifest, null, 2))
    console.log(`corpus: ${manifest.length} images (${faceCount} face photos) in ${OUT}`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
