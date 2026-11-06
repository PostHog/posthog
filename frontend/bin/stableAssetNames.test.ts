import { stableFileName } from './stableChunkNames.mjs'
import { cssGroupFileStem } from './stableCssPlan.mjs'

// Mirrors the immutable-cache rule in PostHog/charts: charts/posthog-app/templates/posthog-django/syncHooks-upload-assets.yaml
const CDN_IMMUTABLE_NAME = /^[A-Za-z0-9]+-[A-Z0-9]{6,}\.(js|css)$/

describe('stable build file names match the charts immutable upload rule', () => {
    it.each(['eager-tailwind', 'eager-global', 'eager-app', 'lazy-0A1B2C3D4E'])('css group %s', (group) => {
        expect(`${cssGroupFileStem(group)}-HHD5DH7J.css`).toMatch(CDN_IMMUTABLE_NAME)
    })

    it.each([
        'chunk-S5F888C59.js',
        'index-DE3U56RC.js',
        'App-AAAA1111.js',
        'DecompressionWorkerManager-BBBB2222.js',
        'sharedChunkAnchors-CCCC3333.js',
        'github-dark-DDDD4444.js',
        'editor.main-EEEE5555.js',
        'hogql_parser_wasm_browser-FFFF6666.js',
        'architecture-7EHR7CIX-GGGG7777.js',
    ])('js output %s', (file) => {
        expect(stableFileName(file, 'source')).toMatch(CDN_IMMUTABLE_NAME)
    })
})
