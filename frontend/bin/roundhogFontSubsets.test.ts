import { createHash } from 'crypto'
import fs from 'fs'
import path from 'path'

import manifest from '../public/fonts/roundhog/manifest.json'

const BRAND_FONTS = path.resolve(__dirname, '../node_modules/@posthog/brand/dist/fonts')

describe('RoundHog latin subsets', () => {
    it.each(Object.entries(manifest.sources))('%s matches the @posthog/brand file it came from', (file, sha256) => {
        const actual = createHash('sha256')
            .update(fs.readFileSync(path.join(BRAND_FONTS, file)))
            .digest('hex')
        // On failure, run: uv run --with fonttools python frontend/bin/subset-roundhog-fonts.py
        expect(actual).toEqual(sha256)
    })
})
