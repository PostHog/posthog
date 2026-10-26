import { createHash } from 'node:crypto'

import { chunkLoaderScript, chunkMapFileContents, chunkMapFileName } from './chunkLoader.mjs'

const CHUNKS = {
    index: ['AAAA1111', 'BBBB2222'],
    Dashboard: ['BBBB2222', 'CCCC3333'],
    PersonScene: ['DDDD4444'],
}

type FakeElement = {
    tag: string
    async?: boolean
    nonce?: string
    src?: string
    rel?: string
    href?: string
    onload?: () => void
    onerror?: () => void
}

const CDN_STATIC = 'https://cdn.example.com/static/'

function runLoader(chunkMapFile: string | null): {
    win: Record<string, any>
    ran: string[]
    preloaded: () => string[]
    scripts: () => FakeElement[]
} {
    const ran: string[] = []
    const appended: FakeElement[] = []
    const win: Record<string, any> = {
        JS_URL: 'https://cdn.example.com',
        ESBUILD_LOAD_SCRIPT: (file: string) => ran.push(file),
    }
    const doc = {
        currentScript: { nonce: 'n0nce' },
        createElement: (tag: string): FakeElement => ({ tag }),
        head: { appendChild: (element: FakeElement) => appended.push(element) },
    }
    // The inline loader runs in the page as a classic script: `window` and `document` are globals.
    new Function('window', 'document', chunkLoaderScript(CHUNKS, chunkMapFile))(win, doc)
    return {
        win,
        ran,
        preloaded: () =>
            appended.filter((e) => e.rel === 'modulepreload').map((e) => (e.href ?? '').replace(CDN_STATIC, '')),
        scripts: () => appended.filter((e) => e.tag === 'script'),
    }
}

describe('chunk loader script', () => {
    // A preload only fetches and parses a chunk. Running every chunk of a scene up front costs more than the
    // browser running them in import order, most of all when the chunks are already in the cache.
    it('preloads the index chunks at boot without running them', () => {
        const { ran, preloaded } = runLoader('chunk-map-index-ABCD1234.js')
        expect(preloaded()).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js'])
        expect(ran).toEqual([])
    })

    it('fetches the external map with the page nonce and CDN base', () => {
        const scripts = runLoader('chunk-map-index-ABCD1234.js').scripts()
        expect(scripts).toHaveLength(1)
        expect(scripts[0].src).toBe('https://cdn.example.com/static/chunk-map-index-ABCD1234.js')
        expect(scripts[0].async).toBe(true)
        expect(scripts[0].nonce).toBe('n0nce')
    })

    it('queues scenes requested before the map arrives and flushes them on load, skipping loaded chunks', () => {
        const { win, preloaded, scripts } = runLoader('chunk-map-index-ABCD1234.js')
        win.ESBUILD_LOAD_CHUNKS('Dashboard')
        expect(preloaded()).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js'])

        // The external file merges the full map into the same global, then the queue drains.
        new Function('window', chunkMapFileContents(CHUNKS))(win)
        scripts()[0].onload?.()

        expect(preloaded()).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js', 'chunk-CCCC3333.js'])
        win.ESBUILD_LOAD_CHUNKS('PersonScene')
        expect(preloaded()).toContain('chunk-DDDD4444.js')
    })

    it('gives up queueing when the map fails to load, so later requests are plain no-ops', () => {
        const { win, preloaded, scripts } = runLoader('chunk-map-index-ABCD1234.js')
        scripts()[0].onerror?.()
        win.ESBUILD_LOAD_CHUNKS('Dashboard')
        expect(preloaded()).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js'])
        expect(win.ESBUILD_PENDING_CHUNK_SCENES).toBeNull()
    })

    it('inlines the whole map and fetches nothing when no external file is given', () => {
        const { win, preloaded, scripts } = runLoader(null)
        win.ESBUILD_LOAD_CHUNKS('Dashboard')
        expect(scripts()).toHaveLength(0)
        expect(preloaded()).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js', 'chunk-CCCC3333.js'])
    })

    it('names the map file by content so a changed map gets a new URL', () => {
        const a = chunkMapFileName('index', CHUNKS)
        const b = chunkMapFileName('index', { ...CHUNKS, Dashboard: ['EEEE5555'] })
        expect(a).toMatch(/^chunk-map-index-[0-9A-F]{8}\.js$/)
        expect(a).not.toBe(b)

        // The hash covers the exact bytes chunkMapFileContents writes to disk, wrapper included,
        // not just the chunk metadata. A future change to the wrapper also gets a new URL.
        const hash = a.match(/^chunk-map-index-([0-9A-F]{8})\.js$/)?.[1]
        const contentHash = createHash('sha256')
            .update(chunkMapFileContents(CHUNKS))
            .digest('hex')
            .slice(0, 8)
            .toUpperCase()
        expect(hash).toBe(contentHash)
    })
})
