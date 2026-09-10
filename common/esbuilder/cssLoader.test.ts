import { CSS_ATTEMPT_TIMEOUT_MS, CSS_PROBE_TIMEOUT_MS, cssLoaderScript } from './cssLoader.mjs'

const CSS_FILE = 'index-ABCD1234.css'
const CSS_FALLBACK = 'index.css?t=99'
const STATIC = 'https://cdn.example.com/static/'

type FakeLink = {
    rel?: string
    crossOrigin?: string
    href?: string
    sheet?: { cssRules?: { length: number } } | null
    addEventListener: (type: string, listener: () => void) => void
    dispatch: (type: string) => void
}

type FakeResponse = { status: number; contentType: string | null }

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
    jsUrl = 'https://cdn.example.com',
    probeResponse = { status: 200, contentType: 'text/css' } as FakeResponse | null,
    probeHangs = false,
}: {
    cssFileFallback?: string
    apiKey?: string | null
    jsUrl?: string
    probeResponse?: FakeResponse | null
    probeHangs?: boolean
} = {}): {
    ready: Promise<boolean>
    links: FakeLink[]
    beacons: Record<string, any>[]
    probes: string[]
} {
    const links: FakeLink[] = []
    const beacons: Record<string, any>[] = []
    const probes: string[] = []
    const win: Record<string, any> = {
        JS_URL: jsUrl,
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
    const fetch = (url: string): Promise<unknown> => {
        probes.push(url)
        if (probeHangs) {
            return new Promise(() => {})
        }
        return probeResponse
            ? Promise.resolve({
                  status: probeResponse.status,
                  headers: { get: () => probeResponse.contentType },
              })
            : Promise.reject(new Error('network'))
    }
    // The inline loader runs in the page as a classic script: these are all globals there.
    new Function(
        'window',
        'document',
        'navigator',
        'console',
        'fetch',
        'AbortController',
        cssLoaderScript(CSS_FILE, cssFileFallback)
    )(
        win,
        doc,
        nav,
        { error: () => {} },
        fetch,
        class {
            signal = {}
            abort = (): void => {}
        }
    )
    return { ready: win.ESBUILD_CSS_READY, links, beacons, probes }
}

/** A stylesheet that really applied has a sheet with rules in it. */
function applyStylesheet(link: FakeLink): void {
    link.sheet = { cssRules: { length: 12 } }
    link.dispatch('load')
}

/** The beacon waits on the probe of the failed URL, so it goes out a few microtasks later. */
async function flushProbes(): Promise<void> {
    for (let tick = 0; tick < 5; tick++) {
        await Promise.resolve()
    }
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
        [
            'gets a sheet with no rules in it, as Chromium builds for an interstitial',
            'loaded but did not apply',
            (link: FakeLink) => {
                link.sheet = { cssRules: { length: 0 } }
                link.dispatch('load')
            },
        ],
    ])('loads the hashless copy and reports when the hashed stylesheet %s', async (_case, reason, fail) => {
        const { links, beacons } = runLoader()
        fail(links[0])
        await flushProbes()

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

    it.each([
        [
            'names the status and the content type of a response that is not CSS',
            { status: 200, contentType: 'text/html' } as FakeResponse | null,
            false,
            { stylesheet_probe: 'answered', stylesheet_status: 200, stylesheet_content_type: 'text/html' },
        ],
        [
            'says the host is unreachable when the probe gets no response',
            null,
            false,
            { stylesheet_probe: 'unreachable' },
        ],
        ['gives up on a probe that hangs, and still sends the beacon', null, true, { stylesheet_probe: 'stalled' }],
    ])('%s', async (_case, probeResponse, probeHangs, expected) => {
        const { links, beacons, probes } = runLoader({ probeResponse, probeHangs })
        links[0].dispatch('load')
        if (probeHangs) {
            jest.advanceTimersByTime(CSS_PROBE_TIMEOUT_MS)
        }
        await flushProbes()

        expect(probes).toEqual([`${STATIC}${CSS_FILE}`])
        expect(beacons).toHaveLength(1)
        expect(beacons[0].properties).toMatchObject(expected)
    })

    it('retries with a fresh query and the app origin, then reports the page unstyled', async () => {
        const { ready, links, beacons } = runLoader()
        for (let attempt = 0; attempt < 4; attempt++) {
            jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        }
        await flushProbes()

        // The third attempt asks for the same file with a query no cache entry and no hung
        // connection has seen. The fourth leaves the static host behind altogether.
        expect(links).toHaveLength(4)
        expect(links[2].href).toMatch(new RegExp(`^${STATIC}index\\.css\\?t=99&retry=\\d+$`))
        expect(links[3].href).toBe(`/static/${CSS_FILE}`)

        await expect(ready).resolves.toBe(false)
        expect(beacons).toHaveLength(4)
        expect(beacons[3].properties).toMatchObject({ $exception_level: 'fatal', stylesheet_attempts: 4 })
    })

    it('adds no app-origin rung when the static files already come from the app origin', () => {
        const { links } = runLoader({ jsUrl: '' })
        for (let attempt = 0; attempt < 3; attempt++) {
            jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        }

        expect(links).toHaveLength(3)
        expect(links[0].href).toBe(`/static/${CSS_FILE}`)
    })

    it('reports ready when a stylesheet abandoned by a timeout lands late', async () => {
        const { ready, links } = runLoader()
        jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        expect(links).toHaveLength(2)

        applyStylesheet(links[0])

        await expect(ready).resolves.toBe(true)
    })

    it('recovers without a beacon or a probe when capture is opted out', async () => {
        const { links, beacons, probes } = runLoader({ apiKey: null })
        links[0].dispatch('error')
        await flushProbes()

        expect(links).toHaveLength(2)
        expect(beacons).toHaveLength(0)
        expect(probes).toHaveLength(0)
    })

    it('still has a retry to fall back on in a dev build with no hashless copy', () => {
        const { links } = runLoader({ cssFileFallback: CSS_FILE })
        links[0].dispatch('error')

        expect(links).toHaveLength(2)
        expect(links[1].href).toMatch(new RegExp(`^${STATIC}index-ABCD1234\\.css\\?retry=\\d+$`))
    })
})
