import { execFileSync } from 'child_process'
import { existsSync } from 'fs'
import { basename, join } from 'path'

interface BrandFace {
    weight: number
    style: string
    subsets: { name: string; url: string; unicodeRange: string }[]
}

// Both run in a plain Node process: the package locates its files through import.meta.url, which
// Jest's CJS transform can't run, and Dart Sass refuses to compile under jsdom.
function brandFacesAndCss(): { faces: BrandFace[]; css: string } {
    const script = `
        const { default: sass } = await import("sass")
        const { roundHogFaces } = await import("@posthog/brand/fonts")
        const { css } = sass.compile(${JSON.stringify(join(__dirname, 'fonts.scss'))})
        console.log(JSON.stringify({ faces: roundHogFaces, css }))
    `
    const out = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
        cwd: join(__dirname, '..', '..'),
        encoding: 'utf8',
    })
    return JSON.parse(out)
}

interface FontFaceRule {
    style: string
    weight: number
    src: string
    unicodeRange: string
}

function roundHogRules(css: string): FontFaceRule[] {
    const rules: FontFaceRule[] = []
    for (const block of css.match(/@font-face\s*{[^}]*}/g) ?? []) {
        if (!/font-family:\s*RoundHog;/.test(block)) {
            continue
        }
        const field = (name: string): string => block.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1].trim() ?? ''
        rules.push({
            style: field('font-style'),
            weight: Number(field('font-weight')),
            src: field('src').match(/url\("?([^")]+)"?\)/)?.[1] ?? '',
            unicodeRange: field('unicode-range'),
        })
    }
    return rules
}

describe('RoundHog @font-face rules', () => {
    const { faces, css } = brandFacesAndCss()
    const rules = roundHogRules(css)

    it('register every @posthog/brand subset with its exact range, and nothing else', () => {
        const expected = faces.flatMap((face) =>
            face.subsets.map((subset) => ({
                style: face.style,
                weight: face.weight,
                file: basename(subset.url),
                unicodeRange: subset.unicodeRange,
            }))
        )
        const actual = rules.map((rule) => ({
            style: rule.style,
            weight: rule.weight,
            file: basename(rule.src),
            unicodeRange: rule.unicodeRange,
        }))
        expect(actual).toEqual(expect.arrayContaining(expected))
        expect(actual).toHaveLength(expected.length)
    })

    it('point at subset files that exist in the installed package', () => {
        for (const rule of rules) {
            expect(existsSync(join(__dirname, rule.src))).toBe(true)
        }
    })
})
