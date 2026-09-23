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

function runLoader({
    cssFileFallback = CSS_FALLBACK,
    apiKey = 'phc_test' as string | null,
    effectiveType = undefined as string | undefined,
} = {}): {
    ready: Promise<boolean>
    links: FakeLink[]
    beacons: Record<string, any>[]
} {
    const links: FakeLink[] = []
    const beacons: Record<string, any>[] = []
    const nav = {
        connection: effectiveType ? { effectiveType } : undefined,
        sendBeacon: (_url: string, body: string) => {
            beacons.push(JSON.parse(body))
            return true
        },
    }
    const win: Record<string, any> = {
        JS_URL: 'https://cdn.example.com',
        JS_POSTHOG_API_KEY: apiKey,
        JS_POSTHOG_HOST: 'https://capture.example.com',
        // A share path, because this loader also runs on exporter.html.
        location: { origin: 'https://app.example.com', href: 'https://app.example.com/shared/sh4r3-t0k3n' },
        localStorage: { getItem: () => null },
        navigator: nav,
    }
    const doc = {
        createElement: (): FakeLink => makeLink(),
        head: { appendChild: (link: FakeLink) => links.push(link) },
    }
    // The inline loader runs in the page as a classic script: these are all globals there.
    new Function('window', 'document', 'navigator', 'console', 'fetch', cssLoaderScript(CSS_FILE, cssFileFallback))(
        win,
        doc,
        nav,
        { error: () => {} },
        () => Promise.resolve()
    )
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
    ])('asks for the hashed stylesheet again when the first attempt %s', (_case, reason, fail) => {
        const { links, beacons } = runLoader()
        fail(links[0])

        // The same file with a query no cache entry and no hung connection has seen.
        expect(links).toHaveLength(2)
        expect(links[1].href).toMatch(new RegExp(`^${STATIC}index-ABCD1234\\.css\\?retry=\\d+$`))
        expect(beacons).toHaveLength(1)
        expect(beacons[0].properties.$exception_list[0]).toMatchObject({
            type: 'StylesheetLoadError',
            value: `App stylesheet ${reason}`,
        })
        expect(beacons[0].properties).toMatchObject({
            stylesheet_href: `${STATIC}${CSS_FILE}`,
            stylesheet_attempt: 1,
            stylesheet_attempts: 4,
            stylesheet_timeout_ms: CSS_ATTEMPT_TIMEOUT_MS,
            $exception_level: 'error',
            $process_person_profile: false,
        })
        // The path can carry a share token, so the beacon must keep the origin only.
        expect(JSON.stringify(beacons[0])).not.toContain('sh4r3-t0k3n')
    })

    it('falls back to the hashless copy and then to the app origin, before reporting the page unstyled', async () => {
        const { ready, links, beacons } = runLoader()
        for (let attempt = 0; attempt < 4; attempt++) {
            jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        }

        expect(links).toHaveLength(4)
        expect(links[2].href).toBe(`${STATIC}${CSS_FALLBACK}`)
        // No JS_URL prefix: the app origin serves the same build, so it answers a CDN outage.
        expect(links[3].href).toBe(`/static/${CSS_FILE}`)

        await expect(ready).resolves.toBe(false)
        expect(beacons).toHaveLength(4)
        expect(beacons[3].properties.$exception_level).toBe('fatal')
    })

    it.each([
        ['slow-2g', 3],
        ['3g', 2],
        ['4g', 1],
    ])('gives an attempt on a %s connection a timeout %i times the base one', (effectiveType, multiplier) => {
        const { links, beacons } = runLoader({ effectiveType })

        jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS * multiplier - 1)
        expect(links).toHaveLength(1)

        jest.advanceTimersByTime(1)
        expect(links).toHaveLength(2)
        expect(beacons[0].properties.stylesheet_timeout_ms).toBe(CSS_ATTEMPT_TIMEOUT_MS * multiplier)
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

    it('still has a retry and the app origin to fall back on in a dev build with no hashless copy', () => {
        const { links } = runLoader({ cssFileFallback: CSS_FILE })
        links[0].dispatch('error')

        expect(links).toHaveLength(2)
        expect(links[1].href).toMatch(new RegExp(`^${STATIC}index-ABCD1234\\.css\\?retry=\\d+$`))
        links[1].dispatch('error')
        expect(links).toHaveLength(3)
        expect(links[2].href).toBe(`/static/${CSS_FILE}`)
        links[2].dispatch('error')
        expect(links).toHaveLength(3)
    })
})
