import { CSS_ATTEMPT_TIMEOUT_MS, cssLoaderScript } from './cssLoader.mjs'

const CSS_FILE = 'index-ABCD1234.css'
const CSS_FALLBACK = 'index.css?t=99'
const STATIC = 'https://cdn.example.com/static/'

type FakeLink = {
    rel?: string
    crossOrigin?: string
    href?: string
    sheet?: object | null
    addEventListener: (type: string, listener: () => void) => void
    dispatch: (type: string) => void
}

function makeLink(): FakeLink {
    const listeners: Record<string, (() => void)[]> = {}
    return {
        sheet: null,
        addEventListener: (type: string, listener: () => void) => {
            ;(listeners[type] ??= []).push(listener)
        },
        dispatch: (type: string) => listeners[type]?.forEach((listener) => listener()),
    }
}

function runLoader({ cssFileFallback = CSS_FALLBACK, apiKey = 'phc_test' as string | null } = {}): {
    ready: Promise<boolean>
    links: FakeLink[]
    beacons: Record<string, any>[]
} {
    const links: FakeLink[] = []
    const beacons: Record<string, any>[] = []
    const win: Record<string, any> = {
        JS_URL: 'https://cdn.example.com',
        JS_POSTHOG_API_KEY: apiKey,
        JS_POSTHOG_HOST: 'https://capture.example.com',
        // A share path, because this loader also runs on exporter.html.
        location: { origin: 'https://app.example.com', href: 'https://app.example.com/shared/sh4r3-t0k3n' },
        localStorage: { getItem: () => null },
    }
    const doc = {
        createElement: (): FakeLink => makeLink(),
        head: { appendChild: (link: FakeLink) => links.push(link) },
    }
    const nav = {
        sendBeacon: (_url: string, body: string) => {
            beacons.push(JSON.parse(body))
            return true
        },
    }
    // The inline loader runs in the page as a classic script: these are all globals there.
    new Function(
        'window',
        'document',
        'navigator',
        'console',
        'fetch',
        cssLoaderScript(CSS_FILE, cssFileFallback)
    )(win, doc, nav, { error: () => {} }, () => Promise.resolve())
    return { ready: win.ESBUILD_CSS_READY, links, beacons }
}

/** A stylesheet that really applied has a `sheet`; a response that is not CSS fires `load` without one. */
function applyStylesheet(link: FakeLink): void {
    link.sheet = {}
    link.dispatch('load')
}

describe('css loader script', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('attaches the hashed stylesheet for CORS and reports ready once it applies', async () => {
        const { ready, links, beacons } = runLoader()
        expect(links).toHaveLength(1)
        expect(links[0]).toMatchObject({ rel: 'stylesheet', crossOrigin: 'anonymous', href: `${STATIC}${CSS_FILE}` })

        applyStylesheet(links[0])

        await expect(ready).resolves.toBe(true)
        expect(beacons).toHaveLength(0)
    })

    it.each([
        ['fails', 'failed to load', (link: FakeLink) => link.dispatch('error')],
        ['stalls', 'stalled', () => jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)],
        ['serves a response that is not CSS', 'loaded but did not apply', (link: FakeLink) => link.dispatch('load')],
    ])('loads the hashless copy and reports when the hashed stylesheet %s', (_case, reason, fail) => {
        const { links, beacons } = runLoader()
        fail(links[0])

        expect(links).toHaveLength(2)
        expect(links[1].href).toBe(`${STATIC}${CSS_FALLBACK}`)
        expect(beacons).toHaveLength(1)
        expect(beacons[0].properties.$exception_list[0]).toMatchObject({
            type: 'StylesheetLoadError',
            value: `App stylesheet ${reason}`,
        })
        expect(beacons[0].properties).toMatchObject({
            stylesheet_href: `${STATIC}${CSS_FILE}`,
            stylesheet_attempt: 1,
            $exception_level: 'error',
            $process_person_profile: false,
        })
        // The path can carry a share token, so the beacon must keep the origin only.
        expect(JSON.stringify(beacons[0])).not.toContain('sh4r3-t0k3n')
    })

    it('retries with a fresh query, then reports the page unstyled once every attempt fails', async () => {
        const { ready, links, beacons } = runLoader()
        for (let attempt = 0; attempt < 3; attempt++) {
            jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        }

        // The last attempt asks for the same file with a query no cache entry and no hung
        // connection has seen.
        expect(links).toHaveLength(3)
        expect(links[2].href).toMatch(new RegExp(`^${STATIC}index\\.css\\?t=99&retry=\\d+$`))

        await expect(ready).resolves.toBe(false)
        expect(beacons).toHaveLength(3)
        expect(beacons[2].properties.$exception_level).toBe('fatal')
    })

    it('reports ready when a stylesheet abandoned by a timeout lands late', async () => {
        const { ready, links } = runLoader()
        jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        expect(links).toHaveLength(2)

        applyStylesheet(links[0])

        await expect(ready).resolves.toBe(true)
    })

    it('recovers without a beacon when capture is opted out', () => {
        const { links, beacons } = runLoader({ apiKey: null })
        links[0].dispatch('error')

        expect(links).toHaveLength(2)
        expect(beacons).toHaveLength(0)
    })

    it('still has a retry to fall back on in a dev build with no hashless copy', () => {
        const { links } = runLoader({ cssFileFallback: CSS_FILE })
        links[0].dispatch('error')

        expect(links).toHaveLength(2)
        expect(links[1].href).toMatch(new RegExp(`^${STATIC}index-ABCD1234\\.css\\?retry=\\d+$`))
        links[1].dispatch('error')
        expect(links).toHaveLength(2)
    })
})
