import { chunkLoaderScript, chunkMapFileContents, chunkMapFileName } from './chunkLoader.mjs'

const CHUNKS = {
    index: ['AAAA1111', 'BBBB2222'],
    Dashboard: ['BBBB2222', 'CCCC3333'],
    PersonScene: ['DDDD4444'],
}

type FakeScript = { async?: boolean; nonce?: string; src?: string; onload?: () => void; onerror?: () => void }

function runLoader(chunkMapFile: string | null): {
    win: Record<string, any>
    loaded: string[]
    scripts: FakeScript[]
} {
    const loaded: string[] = []
    const scripts: FakeScript[] = []
    const win: Record<string, any> = {
        JS_URL: 'https://cdn.example.com',
        ESBUILD_LOAD_SCRIPT: (file: string) => loaded.push(file),
    }
    const doc = {
        currentScript: { nonce: 'n0nce' },
        createElement: (): FakeScript => ({}),
        head: { appendChild: (s: FakeScript) => scripts.push(s) },
    }
    // The inline loader runs in the page as a classic script: `window` and `document` are globals.
    new Function('window', 'document', chunkLoaderScript(CHUNKS, chunkMapFile))(win, doc)
    return { win, loaded, scripts }
}

describe('chunk loader script', () => {
    it('loads the index chunks synchronously at boot', () => {
        const { loaded } = runLoader('chunk-map-index-ABCD1234.js')
        expect(loaded).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js'])
    })

    it('fetches the external map with the page nonce and CDN base', () => {
        const { scripts } = runLoader('chunk-map-index-ABCD1234.js')
        expect(scripts).toHaveLength(1)
        expect(scripts[0].src).toBe('https://cdn.example.com/static/chunk-map-index-ABCD1234.js')
        expect(scripts[0].async).toBe(true)
        expect(scripts[0].nonce).toBe('n0nce')
    })

    it('queues scenes requested before the map arrives and flushes them on load, skipping loaded chunks', () => {
        const { win, loaded, scripts } = runLoader('chunk-map-index-ABCD1234.js')
        win.ESBUILD_LOAD_CHUNKS('Dashboard')
        expect(loaded).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js'])

        // The external file merges the full map into the same global, then the queue drains.
        new Function('window', chunkMapFileContents(CHUNKS))(win)
        scripts[0].onload?.()

        expect(loaded).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js', 'chunk-CCCC3333.js'])
        win.ESBUILD_LOAD_CHUNKS('PersonScene')
        expect(loaded).toContain('chunk-DDDD4444.js')
    })

    it('gives up queueing when the map fails to load, so later requests are plain no-ops', () => {
        const { win, loaded, scripts } = runLoader('chunk-map-index-ABCD1234.js')
        scripts[0].onerror?.()
        win.ESBUILD_LOAD_CHUNKS('Dashboard')
        expect(loaded).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js'])
        expect(win.ESBUILD_PENDING_CHUNK_SCENES).toBeNull()
    })

    it('inlines the whole map and fetches nothing when no external file is given', () => {
        const { win, loaded, scripts } = runLoader(null)
        win.ESBUILD_LOAD_CHUNKS('Dashboard')
        expect(scripts).toHaveLength(0)
        expect(loaded).toEqual(['chunk-AAAA1111.js', 'chunk-BBBB2222.js', 'chunk-CCCC3333.js'])
    })

    it('names the map file by content so a changed map gets a new URL', () => {
        const a = chunkMapFileName('index', CHUNKS)
        const b = chunkMapFileName('index', { ...CHUNKS, Dashboard: ['EEEE5555'] })
        expect(a).toMatch(/^chunk-map-index-[0-9A-F]{8}\.js$/)
        expect(a).not.toBe(b)
    })
})
