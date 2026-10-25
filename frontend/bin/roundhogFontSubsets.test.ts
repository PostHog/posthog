import { createHash } from 'crypto'
import fs from 'fs'
import path from 'path'

import manifest from '../public/fonts/roundhog/manifest.json'

const BRAND_FONTS = path.resolve(__dirname, '../node_modules/@posthog/brand/dist/fonts')

const SUBSET_INPUTS: [string, string, string][] = [
    ...Object.entries(manifest.sources).map(([file, sha256]): [string, string, string] => [
        file,
        path.join(BRAND_FONTS, file),
        sha256,
    ]),
    ['subset-roundhog-fonts.py', path.join(__dirname, 'subset-roundhog-fonts.py'), manifest.script],
]

describe('RoundHog latin subsets', () => {
    it.each(SUBSET_INPUTS)('%s matches the file the subsets came from', (_name, filePath, sha256) => {
        const actual = createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')
        // On failure, run: uv run --with 'fonttools[woff]==4.62.1' python frontend/bin/subset-roundhog-fonts.py
        expect(actual).toEqual(sha256)
    })
})
