import { checkFixedNameFiles } from './fixedNameAssets.mjs'

describe('fixedNameAssets.mjs', () => {
    it.each([
        ['a hashed chunk', ['chunk-S5F888C59.js'], [], { unlisted: [], stale: [] }],
        ['a hashed file in a subdirectory', ['toolbar/toolbar-app-AB12CD34.js'], [], { unlisted: [], stale: [] }],
        [
            'a fixed-name source map or image',
            ['array.js.map', 'logo.png', 'index.html'],
            [],
            { unlisted: [], stale: [] },
        ],
        ['an unlisted fixed-name worker', ['fakeWorker.js'], [], { unlisted: ['fakeWorker.js'], stale: [] }],
        ['an unlisted fixed-name wasm', ['snappy_bg.wasm'], [], { unlisted: ['snappy_bg.wasm'], stale: [] }],
        [
            'a lowercase suffix that is no hash',
            ['web-vitals-attribution.mjs'],
            [],
            { unlisted: ['web-vitals-attribution.mjs'], stale: [] },
        ],
        ['an exact entry', ['array.js'], ['array.js'], { unlisted: [], stale: [] }],
        [
            'an exact entry in another directory',
            ['emoji/array.js'],
            ['array.js'],
            { unlisted: ['emoji/array.js'], stale: ['array.js'] },
        ],
        [
            'a directory entry',
            ['hedgehog-mode/a.js', 'hedgehog-mode/b/c.js'],
            ['hedgehog-mode/'],
            { unlisted: [], stale: [] },
        ],
        ['an exact entry with no file', ['array.js'], ['array.js', 'gone.js'], { unlisted: [], stale: ['gone.js'] }],
        ['a directory entry with no file', [], ['hedgehog-mode/'], { unlisted: [], stale: ['hedgehog-mode/'] }],
    ])('reports %s', (_, distPaths, allowlistEntries, expected) => {
        expect(checkFixedNameFiles(distPaths, allowlistEntries)).toMatchObject(expected)
    })
})
